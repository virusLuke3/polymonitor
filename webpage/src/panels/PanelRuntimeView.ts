import { createContext } from 'preact';
import { useContext } from 'preact/hooks';
import type { PanelRuntimeStatus } from './types';

/** Read-only view of the workspace's existing owner; creates no requests. */
export const PanelRuntimeView = createContext<{ status?: PanelRuntimeStatus; refresh?: () => void } | null>(null);
export const usePanelRuntimeView = () => useContext(PanelRuntimeView);
