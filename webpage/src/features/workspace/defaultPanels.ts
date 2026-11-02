/** Add newly shipped defaults once; an absent, already known panel stays hidden. */
export function reconcileDefaultPanels(activeIds: string[], defaultIds: string[], knownIds: unknown) {
  const known = new Set(Array.isArray(knownIds) ? knownIds.filter((id): id is string => typeof id === 'string') : []);
  return {
    activePanelIds: [...new Set([...activeIds, ...defaultIds.filter(id => !known.has(id))])],
    knownDefaultPanelIds: [...new Set([...known, ...defaultIds])],
  };
}
