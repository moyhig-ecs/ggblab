export {};

declare global {
    interface Window {
        ggblab?: {
            listen?: (message: string) => Promise<void>;
        };
        listen_at_ggblab?: (message: string) => Promise<void>;
    }
}
