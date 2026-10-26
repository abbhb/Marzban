import { Alert, AlertIcon, Box, Button, HStack, Select, Text, VStack } from "@chakra-ui/react";
import { useState } from "react";
import { useQuery } from "react-query";
import { useTranslation } from "react-i18next";
import { fetch, errorMessage } from "service/http";

export type PlanGroupMembers = Record<string, string[]>;

export const PlanGroupEditor = ({ value, onChange, inboundTags }: {
  value: PlanGroupMembers; onChange: (value: PlanGroupMembers) => void; inboundTags: string[];
}) => {
  const { t } = useTranslation();
  const catalog = useQuery(["plan-group-catalog"], () => fetch<{ groups: string[] }>("/commerce/admin/group-catalog"), { retry: false });
  const [group, setGroup] = useState("");
  const [dragged, setDragged] = useState<string | null>(null);
  const selectedGroup = group || catalog.data?.groups[0] || "";
  const choices = [...inboundTags.map(tag => `inbound:${tag}`), "external"];
  const label = (ref: string) => ref === "external" ? "MGMA · External" : ref.slice(8);
  const members = value[selectedGroup];
  const update = (next: string[]) => onChange({ ...value, [selectedGroup]: next });
  const place = (ref: string, index = members?.length || 0) => {
    if (!choices.includes(ref)) return;
    const previous = (members || []).indexOf(ref);
    const next = (members || []).filter(item => item !== ref);
    if (previous >= 0 && previous < index) index -= 1;
    next.splice(Math.min(index, next.length), 0, ref);
    update(next);
  };
  const drop = (event: React.DragEvent, index?: number) => {
    event.preventDefault(); event.stopPropagation();
    if (dragged) place(dragged, index);
    setDragged(null);
  };
  const move = (index: number, step: number) => {
    const next = [...(members || [])];
    [next[index], next[index + step]] = [next[index + step], next[index]];
    update(next);
  };
  return <VStack align="stretch" spacing={3} p={4} layerStyle="glassSubtle" rounded="xl">
    <Text fontWeight="semibold">{t("planGroups.title")}</Text>
    <Text fontSize="sm" color="fg.muted">{t("planGroups.help")}</Text>
    {catalog.error ? <Alert status="error"><AlertIcon />{errorMessage(catalog.error, t("commerce.loadError"))}</Alert> : null}
    <Select aria-label={t("planGroups.group")} value={selectedGroup} onChange={e => setGroup(e.target.value)} isDisabled={catalog.isLoading}>
      {catalog.data?.groups.map(name => <option key={name} value={name}>{name}{value[name] ? ` · ${t("planGroups.custom")}` : ""}</option>)}
    </Select>
    <Text fontSize="sm">{t("planGroups.available")}</Text>
    <HStack flexWrap="wrap" gap={2}>
      {choices.map(ref => <Button key={ref} type="button" size="sm" variant="outline" draggable
        onDragStart={e => { e.dataTransfer.setData("application/x-marzban-member", ref); setDragged(ref); }} onDragEnd={() => setDragged(null)}
        onClick={() => place(ref)} isDisabled={!selectedGroup || (members || []).includes(ref)}
        aria-label={`${t("planGroups.add")} ${label(ref)}`}>+ {label(ref)}</Button>)}
    </HStack>
    <Box onDragOver={e => e.preventDefault()} onDrop={e => drop(e)} minH="100px" borderWidth="1px" borderStyle="dashed" rounded="lg" p={3}>
      {members === undefined ? <Text color="fg.muted" fontSize="sm">{t("planGroups.default")}</Text> : !members.length ? <Text color="fg.muted" fontSize="sm">{t("planGroups.empty")}</Text> : null}
      <VStack align="stretch" spacing={2}>
        {(members || []).map((ref, index) => <HStack key={ref} draggable onDragStart={e => { e.stopPropagation(); e.dataTransfer.setData("application/x-marzban-member", ref); setDragged(ref); }} onDragEnd={() => setDragged(null)}
          onDragOver={e => e.preventDefault()} onDrop={e => drop(e, index)} p={2} borderWidth="1px" rounded="lg" flexWrap="wrap">
          <Text flex="1" overflowWrap="anywhere">{index + 1}. {label(ref)}</Text>
          <Button type="button" size="sm" aria-label={`${t("planGroups.up")} ${label(ref)}`} isDisabled={index === 0} onClick={() => move(index, -1)}>↑</Button>
          <Button type="button" size="sm" aria-label={`${t("planGroups.down")} ${label(ref)}`} isDisabled={index === (members?.length || 0) - 1} onClick={() => move(index, 1)}>↓</Button>
          <Button type="button" size="sm" onClick={() => update((members || []).filter(m => m !== ref))}>{t("planGroups.remove")}</Button>
        </HStack>)}
      </VStack>
    </Box>
    <HStack flexWrap="wrap">
      <Button type="button" size="sm" onClick={() => update([])} isDisabled={!selectedGroup}>{t("planGroups.clear")}</Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => { const next = { ...value }; delete next[selectedGroup]; onChange(next); }}>{t("planGroups.reset")}</Button>
    </HStack>
  </VStack>;
};
