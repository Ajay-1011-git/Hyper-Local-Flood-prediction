"""WeatherNext 2 Cyclones Mini forecast ingestion (T1A.2/T1A.3 amendment).

Replaces the never-runnable live-GenCast-inference path as the primary
real-data source. The backend does not run inference; it loads a `.nc` file
produced by manually running `wn2_demo.ipynb` in Colab ahead of time. See
`loader.py` and `parser.py`.
"""
