import { LocalInbound } from "types/Commerce";
import { PlanGroupMembers } from "./PlanGroupEditor";

export const pruneLocalPlan = (
  tags: string[], selections: Record<string, string[]>, groups: PlanGroupMembers,
  catalog: LocalInbound[], groupNames?: string[]
) => {
  const available = new Map(catalog.map(item => [item.tag, new Set(item.nodes.map(node => node.id))]));
  const inboundTags: string[] = [];
  const localNodeSelections: Record<string, string[]> = {};
  for (const tag of tags) {
    const nodes = available.get(tag);
    if (!nodes) continue;
    if (selections[tag] !== undefined) {
      const ids = selections[tag].filter(id => nodes.has(id));
      if (!ids.length) continue;
      localNodeSelections[tag] = [...new Set(ids)];
    }
    inboundTags.push(tag);
  }
  const groupMembers = Object.fromEntries(Object.entries(groups)
    .filter(([name]) => !groupNames || groupNames.includes(name))
    .map(([name, refs]) => [name, [...new Set(refs.filter(ref => ref === "external" ||
      (ref.startsWith("inbound:") && inboundTags.includes(ref.slice(8)))))]]));
  return { inboundTags, localNodeSelections, groupMembers };
};
