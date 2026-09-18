import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { Data } from '../shared/types';
import { previewCall } from './preview';

export const native = '__TAURI_INTERNALS__' in window;
// 동봉된 Agent 는 별도로 패키징되는 exe 라서 앱보다 오래된 빌드일 수 있다. 그러면
// 화면은 멀쩡한데 명령만 거부당하고, 메시지만으로는 원인을 알 수 없다. status 가
// 알려 준 명령 목록으로 부르기 전에 걸러 낸다.
const REBUILD_HINT = 'scripts/dev-desktop.ps1 -RebuildAgent 로 사이드카를 다시 패키징하세요.';
let agentOperations: string[] | null = null;

function staleAgent(operation: string): string | null {
  if (!native || !agentOperations) return null;
  if (agentOperations.includes(operation)) return null;
  return `동봉된 Agent 가 '${operation}' 을 모릅니다. 앱보다 오래된 빌드입니다 — ${REBUILD_HINT}`;
}

export async function call<T = Data>(operation: string, args: Data = {}): Promise<T> {
  const stale = staleAgent(operation);
  if (stale) throw new Error(stale);
  if (!native) return previewCall(operation, args);
  try {
    return await invoke<T>('dispatch', {operation, args});
  } catch (error) {
    // 목록을 아직 못 받았거나(구 Agent 는 이 필드를 내지 않는다) Rust 쪽에서 막힌 경우.
    const text = String(error);
    if (text.includes('모릅니다') || text.includes('허용되지 않은 명령')
        || text.includes('Unsupported Agent operation')) {
      throw new Error(`${text} (${REBUILD_HINT})`);
    }
    throw error;
  }
}

export function setAgentOperations(data: Data) {
  agentOperations = Array.isArray(data.operations) ? data.operations as string[] : null;
}

export async function listenToAgent(progress: (data: Data) => void, failure: (error: string) => void) {
  await listen<Data>('agent-progress', event => progress(event.payload));
  await listen<string>('agent-failure', event => failure(event.payload));
}
