// Shared lightweight types for ggblab frontend

/** Minimal shape of the GeoGebra applet API used by the widget code. */
export interface IAppletApi {
  evalCommandGetLabels?: (payload: any) => any;
  registerObjectUpdateListener?: (name: string, cb: () => void) => any;
  unregisterObjectUpdateListener?: (name: string) => any;
  getValueString?: (name: string) => string | null;
  setSize?: (w: number, h: number) => void;
  recalculateEnvironments?: () => void;
  [method: string]: any;
}

/** Loose resource bag interface matching `Resources` used in `src/widget.tsx`. */
export interface IResources {
  kernelId?: string;
  commTarget?: string;
  socketPath?: string | null;
  wsPort?: number;
  kernel2?: any;
  kernelManager?: any;
  kernelConn?: any;
  comm?: any;
  widgetComm?: any;
  appletApi?: IAppletApi | null;
  // Unregister function returned by `registerWidgetCommTargets`.
  unregisterWidgetCommTargets?: (() => void) | null;
  observer?: MutationObserver | null;
  resizeHandler?: (() => void) | null;
  closeHandler?: (() => void) | null;
  metaViewport?: HTMLMetaElement | null;
  scriptTag?: HTMLScriptElement | null;
  [k: string]: any;
}

/** Options required for registering widget comm targets. */
export interface IRegisterWidgetCommOptions {
  callRemoteSocketSend: (message: string) => Promise<void>;
  kernel2: any;
  socketPath: string | null;
  wsUrl: string;
  getAppletApi: () => IAppletApi | null;
  res?: IResources;
  dbg?: (...args: any[]) => void;
}
