import { Accordion, AccordionButton, AccordionIcon, AccordionItem, AccordionPanel, Alert, AlertDescription, AlertIcon, Badge, Box, Button, HStack, Spinner, Text, useToast, VStack } from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage, fetch } from "service/http";

type GroupSettings = { group_names: string[]; template_group_names: string[]; enabled: boolean; revision: number; fixed_external_group: string };

export const GroupOrderWorkspace = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [settings, setSettings] = useState<GroupSettings | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dirty = !!settings && JSON.stringify(groups) !== JSON.stringify(settings.group_names);
  const apply = (value: GroupSettings) => { setSettings(value); setGroups(value.group_names); };
  const load = async () => {
    setBusy(true); setError("");
    try { apply(await fetch<GroupSettings>("/subscription/group-order")); }
    catch (error) { setError(errorMessage(error, t("commerce.loadError"))); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const save = async (reset = false) => {
    if (!settings || busy) return;
    setBusy(true); setError("");
    try {
      apply(await fetch<GroupSettings>("/subscription/group-order", { method: "PUT", body: { group_names: reset ? null : groups, revision: settings.revision } }));
      toast({ title: t("groups.saved"), status: "success", position: "top" });
    } catch (error) { setError(errorMessage(error, t("commerce.saveError"))); }
    finally { setBusy(false); }
  };
  const move = (index: number, target: number) => {
    const next = [...groups];
    next.splice(target, 0, ...next.splice(index, 1));
    setGroups(next);
  };
  return <Accordion allowToggle layerStyle="glass" rounded="2xl">
    <AccordionItem border="none">
      <h2><AccordionButton p={{ base: 4, md: 6 }} rounded="2xl">
        <Box flex="1" textAlign="start" fontWeight="semibold">{t("groups.title")}</Box>
        {settings && <Badge mx={3} colorScheme={settings.enabled ? "green" : "gray"}>{t(settings.enabled ? "groups.custom" : "groups.template")}</Badge>}
        <AccordionIcon />
      </AccordionButton></h2>
      <AccordionPanel px={{ base: 4, md: 6 }} pb={6}>
        <VStack align="stretch" spacing={3}>
          <Text fontSize="sm" color="fg.muted">{t("groups.help")}</Text>
          {error && <Alert status="error" role="alert" rounded="xl"><AlertIcon /><AlertDescription>{error}</AlertDescription></Alert>}
          {!settings && busy && <Spinner />}
          <VStack as="ol" m={0} p={0} align="stretch" spacing={2} aria-label={t("groups.title")}>
            {groups.map((name, index) => <HStack as="li" key={name} p={2} borderWidth="1px" rounded="lg" listStyleType="none" flexWrap="wrap">
              <Text minW="24px" color="fg.muted" fontSize="sm">{index + 1}</Text>
              <Text flex="1" minW="120px" overflowWrap="anywhere">{name}</Text>
              <HStack spacing={1}>
                <Button size="sm" variant="ghost" isDisabled={busy || index === 0} aria-label={t("groups.topLabel", { name })} onClick={() => move(index, 0)}>{t("groups.top")}</Button>
                <Button size="sm" variant="outline" isDisabled={busy || index === 0} aria-label={t("groups.upLabel", { name })} onClick={() => move(index, index - 1)}>{t("groups.up")}</Button>
                <Button size="sm" variant="outline" isDisabled={busy || index === groups.length - 1} aria-label={t("groups.downLabel", { name })} onClick={() => move(index, index + 1)}>{t("groups.down")}</Button>
              </HStack>
            </HStack>)}
          </VStack>
          <HStack p={3} borderWidth="1px" rounded="lg" flexWrap="wrap">
            <Text>{t("groups.external")}</Text><Badge>{t("groups.fixed")}</Badge>
          </HStack>
          <HStack flexWrap="wrap">
            <Button colorScheme="primary" onClick={() => void save()} isLoading={busy} isDisabled={!dirty}>{t("groups.save")}</Button>
            <Button variant="outline" onClick={() => void load()} isDisabled={busy}>{t("rules.reload")}</Button>
            <Button variant="ghost" onClick={() => void save(true)} isDisabled={busy || !settings || (!settings.enabled && !dirty)}>{t("groups.reset")}</Button>
          </HStack>
        </VStack>
      </AccordionPanel>
    </AccordionItem>
  </Accordion>;
};
