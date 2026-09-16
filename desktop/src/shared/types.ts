/** Flexible JSON records received from the Python sidecar. */
export type Data = Record<string, any>;
export type AgentCall = <T = Data>(operation: string, args?: Data) => Promise<T>;
export type ActionBinder = (
  id: string, operation: string, args?: () => Data, target?: string,
  after?: (result: Data) => void, disabled?: () => boolean,
) => void;
