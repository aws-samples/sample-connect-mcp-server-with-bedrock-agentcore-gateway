/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PRIVY_APP_ID: string;
  readonly VITE_PRIVY_SIGNER_ID: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
