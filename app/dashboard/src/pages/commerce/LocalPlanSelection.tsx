import {
  Alert, AlertDescription, Badge, Box, Button, Checkbox, Collapse, HStack, Text, VStack,
} from "@chakra-ui/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { LocalInbound } from "types/Commerce";

export const LocalPlanSelection = ({
  inbounds, inboundTags, selections, onChange,
}: {
  inbounds: LocalInbound[];
  inboundTags: string[];
  selections: Record<string, string[]>;
  onChange: (tags: string[], selections: Record<string, string[]>) => void;
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const change = (tag: string, checked: boolean, ids?: string[]) => {
    const next = { ...selections };
    delete next[tag];
    if (checked && ids) next[tag] = ids;
    onChange(checked ? Array.from(new Set([...inboundTags, tag])) : inboundTags.filter(item => item !== tag), next);
  };
  const select = (tag: string, ids: string[]) => change(tag, ids.length > 0, ids);

  return (
    <VStack align="stretch" spacing="3">
      <Text fontSize="sm" color="fg.muted">{t("commerce.localRoutesHelp")}</Text>
      {inbounds.map(inbound => {
        const checked = inboundTags.includes(inbound.tag);
        const ids = selections[inbound.tag];
        const selected = new Set(ids || inbound.nodes.map(node => node.id));
        const missing = (ids || []).filter(id => !inbound.nodes.some(node => node.id === id));
        const open = expanded[inbound.tag] ?? Boolean(ids);
        return (
          <Box key={inbound.tag} layerStyle="glassSubtle" p="3" rounded="xl">
            <HStack justify="space-between" flexWrap="wrap" gap="2">
              <Checkbox
                isChecked={checked}
                isIndeterminate={checked && Boolean(ids)}
                onChange={event => change(inbound.tag, event.target.checked)}
              >
                {inbound.tag}
              </Checkbox>
              <Button size="sm" variant="ghost" minH="36px"
                aria-label={t("commerce.localExpand", { tag: inbound.tag })}
                aria-expanded={open && checked}
                isDisabled={!checked}
                onClick={() => setExpanded({ ...expanded, [inbound.tag]: !open })}
              >
                {checked && ids ? t("commerce.localSelected", { count: ids.length }) : t("commerce.localAll")}
                {checked && (open ? " −" : " +")}
              </Button>
            </HStack>
            <Collapse in={open && checked}>
              <VStack align="stretch" spacing="3" mt="3">
                <HStack flexWrap="wrap" gap="2">
                  <Button size="sm" variant={!ids ? "solid" : "outline"}
                    colorScheme="primary" onClick={() => change(inbound.tag, true)}>
                    {t("commerce.localAll")}
                  </Button>
                  {[true, false].map(ipv6 => {
                    const familyIds = inbound.nodes.filter(node => node.ipv6 === ipv6).map(node => node.id);
                    return familyIds.length > 0 && (
                      <Button key={String(ipv6)} size="sm" variant="outline"
                        onClick={() => select(inbound.tag, familyIds)}>
                        {t(ipv6 ? "commerce.localOnlyIpv6" : "commerce.localOnlyIpv4")}
                      </Button>
                    );
                  })}
                </HStack>
                {missing.length > 0 && (
                  <Alert status="warning" rounded="lg" flexWrap="wrap" gap="2">
                    <AlertDescription fontSize="sm" flex="1">
                      {t("commerce.localUnavailable", { count: missing.length })}
                    </AlertDescription>
                    <Button size="sm" onClick={() => select(inbound.tag, (ids || []).filter(id => !missing.includes(id)))}>
                      {t("commerce.localRemoveUnavailable")}
                    </Button>
                  </Alert>
                )}
                {!inbound.nodes.length && <Text fontSize="sm" color="fg.muted">{t("commerce.localEmpty")}</Text>}
                {inbound.nodes.map(node => (
                  <Checkbox key={node.id} isChecked={selected.has(node.id)} alignItems="start"
                    onChange={event => select(inbound.tag, event.target.checked
                      ? Array.from(new Set([...selected, node.id]))
                      : [...selected].filter(id => id !== node.id))}>
                    <Text as="span" overflowWrap="anywhere">{node.name}</Text>
                    {!node.enabled && <Badge ms="2">{t("commerce.localDisabled")}</Badge>}
                  </Checkbox>
                ))}
              </VStack>
            </Collapse>
          </Box>
        );
      })}
    </VStack>
  );
};
