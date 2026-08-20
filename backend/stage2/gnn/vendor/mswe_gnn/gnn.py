"""Vendored from RBTV1/mSWE-GNN (MIT License, Copyright (c) 2024 Roberto
Bentivoglio), fetched directly from github.com/RBTV1/mSWE-GNN in-session
(2026-08-20) -- not reconstructed from memory. See LICENSE in this
directory for the full license text (kept verbatim, unmodified).

TRIMMED from the original models/gnn.py: the multiscale `MSGNN` class and
its `from utils.dataset import create_scale_mask` import were removed.
Per an explicit human decision (2026-08-20 amendment), this project uses
the single-scale `GNN(type_GNN="SWEGNN")` architecture only -- MSGNN
needs multiscale mesh-coarsening machinery (`utils/dataset.py` and
related graph-construction code) this project's mesh (T2.4, a regular
grid) doesn't build. `GNN` and `SWEGNN` below are otherwise byte-identical
to the original file -- no other lines changed.
"""

# Libraries
import torch
import torch.nn as nn
from stage2.gnn.vendor.mswe_gnn.models import BaseFloodModel, make_mlp, activation_functions
from torch_geometric.nn import ChebConv, TAGConv, GATConv
from torch import Tensor
from torch_geometric.utils import scatter
from torch.linalg import vector_norm
from typing import Optional


class GNN(BaseFloodModel):
    '''
    GNN encoder-processor-decoder
    ------
    num_node_features: int, number of features per node
    num_edge_features: int, number of features per edge
    hid_features: int, number of features per node (and edge) in the GNN layers
    K: int, K-hop neighbourhood
    n_GNN_layers: int, number of GNN layers
    dropout: float, add dropout layer in decoder
    type_GNN: str (default='SWEGNN'), specifies the type of GNN model
        options: 
            "GNN_A" : Adjacency as graph shift operator 
            "GNN_L" : Laplacian as graph shift operator
            "GAT"   : Graph Attention, i.e., learned shift operator
            "SWEGNN": learned graph shift operator
    edge_mlp: bool, adds MLP as edge encoder (valid only for 'SWEGNN')
    mlp_layers: int (default=2), number of MLP layers in the GNN processor
    mlp_activation: str (default='prelu'), activation function for the MLP layers
    gnn_activation: str (default='tanh'), activation function for the GNN layers
    with_WL: bool (default=False), adds water level as static input
    normalize: bool (default=True), normalize learned fluxes in SWE-GNN
    with_filter_matrix: bool (default=True), adds filter matrix to the GNN processor (i.e., adds the H in the graph convolution S*X*H)
    with_gradient: bool (default=True), adds the gradient of the water variables in the GNN processor
    base_model_kwargs: dict, additional arguments for the BaseFloodModel, e.g., learned_residuals, seed, residuals_base, etc.
    '''
    def __init__(self, num_node_features, num_edge_features, hid_features=32, K=2, n_GNN_layers=2, type_GNN="SWEGNN", 
                 mlp_layers=1, mlp_activation='prelu', gnn_activation='prelu', dropout=0, 
                 with_WL=True, normalize=True, with_filter_matrix=True, edge_mlp=True,
                 with_gradient=True, **base_model_kwargs):
        super(GNN, self).__init__(**base_model_kwargs)
        self.type_model = "GNN"
        self.hid_features = hid_features
        self.num_node_features = num_node_features
        self.num_edge_features = num_edge_features
        self.type_GNN = type_GNN
        self.edge_mlp = edge_mlp
        self.with_WL = with_WL
        self.gnn_activation = gnn_activation
        self.dynamic_node_features = self.previous_t*self.out_dim
        self.static_node_features = num_node_features - self.dynamic_node_features + self.with_WL
        
        # Edge encoder
        if type_GNN == "SWEGNN" and edge_mlp:
            self.num_edge_features = hid_features
            self.edge_encoder = make_mlp(num_edge_features, hid_features, hid_features, n_layers=mlp_layers, bias=True,
                                         activation=mlp_activation, device=self.device)
        
        # Node encoder
        if type_GNN == "SWEGNN":
            self.dynamic_node_encoder = make_mlp(self.dynamic_node_features, hid_features, hid_features, n_layers=mlp_layers,
                                        activation=mlp_activation, device=self.device)
    
            self.static_node_encoder = make_mlp(
                self.static_node_features, hid_features, hid_features, n_layers=2, bias=True,
                activation=mlp_activation, device=self.device)
        else:
            self.node_encoder = make_mlp(num_node_features + self.with_WL, hid_features, hid_features, n_layers=mlp_layers, bias=True,
                                        activation=mlp_activation, device=self.device)
        
        # GNN
        self.gnn_processor = self._make_gnn(hid_features, K_hops=K, n_GNN_layers=n_GNN_layers, n_layers=mlp_layers, 
                                            activation=mlp_activation, bias=True, type_GNN=type_GNN, 
                                            normalize=normalize, with_filter_matrix=with_filter_matrix,
                                            with_gradient=with_gradient)

        self.gnn_activation = activation_functions(gnn_activation, device=self.device)
        
        # Decoder
        self.node_decoder = make_mlp(hid_features, self.out_dim, hid_features, n_layers=mlp_layers, dropout=dropout,
                                     activation=mlp_activation, device=self.device)

    def _make_gnn(self, hidden_size, K_hops=1, n_GNN_layers=1, type_GNN='SWEGNN', **swegnn_kwargs):
        """Builds GNN module"""
        convs = nn.ModuleList()
        for l in range(n_GNN_layers):
            if type_GNN == "GNN_L":
                convs.append(ChebConv(hidden_size, hidden_size, K=K_hops))
            elif type_GNN == "GNN_A":
                convs.append(TAGConv(hidden_size, hidden_size, K=K_hops))
            elif type_GNN == "GAT":
                convs.append(GATConv(hidden_size, hidden_size, heads=1))
            elif type_GNN == "SWEGNN":
                convs.append(SWEGNN(hidden_size, hidden_size, self.num_edge_features, K=K_hops, 
                            device=self.device, **swegnn_kwargs))
            else:
                raise("Only 'GNN_A', 'GNN_L', 'GAT', and 'SWEGNN' are valid for now")
        return convs
    
    def forward(self, graph):
        """Build encoder-decoder block"""    
        x = graph.x.clone()
        edge_index = graph.edge_index
        edge_attr = graph.edge_attr
        
        # 1. Node and edge encoder
        if self.type_GNN == "SWEGNN" and self.edge_mlp:
            edge_attr = self.edge_encoder(edge_attr)
        
        x0 = x
        x_s = x[:,:self.static_node_features-self.with_WL]
        x_d = x[:,self.static_node_features-self.with_WL:]

        if self.with_WL:
            # Add water level as static input
            WL = x_s[:,-1] + x_d[:,-self.out_dim]
            x_s = torch.cat((x_s, WL.unsqueeze(-1)), 1)
        
        if self.type_GNN == "SWEGNN":
            x_s = self.static_node_encoder(x_s)
            x = x_d = self.dynamic_node_encoder(x_d)
        else:
            x = self.node_encoder(torch.cat((x_s, x_d), 1))

        # 2. Processor 
        for i, conv in enumerate(self.gnn_processor):
            if self.type_GNN == "SWEGNN":
                x = conv(x_s, x_d, edge_index, edge_attr)
            else:
                x = conv(x=x, edge_index=edge_index)

            # Add non-linearity
            if self.gnn_activation is not None:
                x = self.gnn_activation(x)

            x_d = x

        # 3. Decoder
        x = self.node_decoder(x)
                    
        # Add residual connections
        x = x + self._add_residual_connection(x0)
        
        # ReLU because of negative water depth or discharge
        x = torch.relu(x)

        # Mask very small water depth
        x = self._mask_small_WD(x, epsilon=0.0001)

        return x
    
class SWEGNN(nn.Module):
    r"""Shallow Water Equations inspired Graph Neural Network

    .. math::
        \mathbf{x}^{\prime}_{di} = \mathbf{x}_{di} + \sum_{j \in \mathcal{N}(i)} 
        \mathbf{s}_{ij} \odot (\mathbf{x}_{dj} - \mathbf{x}_{di})

        \mathbf{s}_{ij} = MLP \left(\mathbf{x}_{si}, \mathbf{x}_{sj},
        \mathbf{x}_{di}, \mathbf{x}_{dj},
        \mathbf{e}_{ij}\right)
    """
    def __init__(self, static_node_features: int, dynamic_node_features: int, edge_features: int, 
                 K: int = 2, normalize=True, with_filter_matrix=True, with_gradient=True,
                 upwind_mode=False, device='cpu', **mlp_kwargs):
        super().__init__()
        self.edge_features = edge_features
        self.edge_input_size = edge_features + static_node_features*2 + dynamic_node_features*2
        self.edge_output_size = dynamic_node_features
        hidden_size = self.edge_output_size*2
        self.normalize = normalize
        self.K = K
        self.with_filter_matrix = with_filter_matrix
        self.device = device
        self.with_gradient = with_gradient
        self.upwind_mode = upwind_mode
        
        self.edge_mlp = make_mlp(self.edge_input_size, self.edge_output_size,
                                hidden_size=hidden_size, device=device, **mlp_kwargs)

        if with_filter_matrix:
            self.filter_matrix = torch.nn.ModuleList([
                nn.Linear(dynamic_node_features, dynamic_node_features, bias=False, device=device) for _ in range(K+1)
            ])


    def forward(self, 
                x_s: Tensor, 
                x_d: Tensor, 
                edge_index: Tensor, 
                edge_attr: Optional[Tensor]=None) -> Tensor:
        '''
        x_s: static node features
        x_d: dynamic node features
        edge_index: edge indices
        edge_attr: edge features
        '''
        row = edge_index[0]
        col = edge_index[1]
        num_nodes = x_d.size(0)
        if self.with_filter_matrix:
            out = self.filter_matrix[0].forward(x_d.clone())
        else:
            out = x_d.clone()
        
        for k in range(self.K):
            # Filter out zero values
            mask = out.sum(1) != 0
            mask_row = mask[row]
            mask_col = mask[col]
            edge_index_mask = mask_row + mask_col

            # Edge update
            e_ij = torch.cat([x_s[row][edge_index_mask], 
                                x_s[col][edge_index_mask], 
                                x_d[row][edge_index_mask], 
                                x_d[col][edge_index_mask]], 1)
            
            if self.edge_features > 0:
                e_ij = torch.cat([e_ij, edge_attr[edge_index_mask]], 1)

            s_ij = self.edge_mlp(e_ij)
            
            if self.normalize:
                s_ij = s_ij/vector_norm(s_ij, dim=1, keepdim=True)
                s_ij.masked_fill_(torch.isnan(s_ij), 0)

            # Node update
            if self.with_gradient:
                hydraulic_gradient = out[col][edge_index_mask]-out[row][edge_index_mask]
                if self.upwind_mode:
                    hydraulic_gradient[hydraulic_gradient<0] = 0
                shift_sum = hydraulic_gradient*s_ij
            else:
                shift_sum = s_ij*out[row][edge_index_mask]

            scattered = scatter(shift_sum, col[edge_index_mask], reduce='sum', 
                          dim=0, dim_size=num_nodes)

            if self.with_filter_matrix:
                scattered = self.filter_matrix[k+1].forward(scattered)

            out = out + scattered
        
        return out

    def __repr__(self):
        return '{}(node_features={}, edge_features={}, K={}, with_filter_matrix={}, with_gradient={})'.format(
            self.__class__.__name__, self.edge_output_size, 
            self.edge_features, self.K, self.with_filter_matrix,
            self.with_gradient)