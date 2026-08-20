/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_STAGE1A_BASE_URL?: string
  readonly VITE_STAGE1B_BASE_URL?: string
  readonly VITE_STAGE2_BASE_URL?: string
  readonly VITE_STAGE3_BASE_URL?: string
  readonly VITE_STAGE4_BASE_URL?: string
  readonly VITE_WS_BASE_URL?: string
  readonly VITE_SITE_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
