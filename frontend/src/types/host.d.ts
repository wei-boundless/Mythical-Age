export {};

declare global {
  var __MYTHICAL_AGENT_HOST__:
    | {
        apiBase: string;
        frontendUrl: string;
        backendHealthUrl: string;
        frontendPort: number;
        backendPort: number;
        mode: "dev";
        hostMode?: "web" | "desktop";
        localRuntimeAvailable?: boolean;
        vibeCodingHostAvailable?: boolean;
      }
    | undefined;

  interface Window {
    mythicalAgentHost?:
      | {
          getConfig: () => {
            apiBase: string;
            frontendUrl: string;
            backendHealthUrl: string;
            frontendPort: number;
            backendPort: number;
            mode: "dev";
            hostMode?: "web" | "desktop";
            localRuntimeAvailable?: boolean;
            vibeCodingHostAvailable?: boolean;
          };
        }
      | undefined;
  }
}
