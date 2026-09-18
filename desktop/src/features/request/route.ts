import type { Data } from '../../shared/types';
import { Playback } from '../../shared/console';
import { mountFlow, type FlowCanvas } from '../../shared/flow';
import { mountTrace } from '../../shared/trace';
import { nodeControls, routeAction, type RouteAction, type RouteControls } from './controls';
import { routeCard, idleRouteHtml, type MapMode } from './view';

interface RouteSnapshot { connection: Data | null; record: Data | null; controls: RouteControls }

/** Owns map rendering/playback; request state and service calls stay with the controller. */
export function createRequestRoute(root: HTMLElement, playbackRoot: HTMLElement,
  snapshot: () => RouteSnapshot, onAction: (action: RouteAction) => void) {
  const playback = new Playback(playbackRoot, 'req');
  let flow: FlowCanvas | null = null;
  let mode: MapMode = 'checks';

  function render() {
    const {connection, record, controls} = snapshot();
    const card = record ? routeCard(record, connection, mode, controls) : idleRouteHtml(connection, controls);
    root.innerHTML = card.html;
    flow = mountFlow(root, card.flow, playback);
    if (card.trace) mountTrace(root, card.trace, playback);
    playback.set(card.ctx);
  }

  root.addEventListener('click', event => {
    const button = (event.target as HTMLElement).closest<HTMLElement>('button[data-map]');
    const value = button?.dataset.map;
    if (value !== 'checks' && value !== 'equations') return;
    mode = value;
    render();
  });
  root.addEventListener('flownode', event => {
    const detail = (event as CustomEvent).detail;
    if (!detail) return;
    const action = routeAction(snapshot().controls, detail.node, detail.value);
    if (action) onAction(action);
  });

  return {
    render,
    openRelayMenu: () => flow?.openNodeMenu('R'),
    syncControls: () => {
      if (!flow) return;
      const {record, controls} = snapshot();
      const nodes = nodeControls(controls, record ? (record.lab_scenario || 'normal') : controls.scenario, !!record);
      flow.setNodeMenu(nodes.nodeMenu);
      flow.setNodeState(nodes.nodeState);
    },
  };
}
