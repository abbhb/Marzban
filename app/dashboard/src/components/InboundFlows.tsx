import { Alert, AlertIcon, Button, HStack, Select, Spinner, Text, VStack, useToast } from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch, errorMessage } from "service/http";

type Settings = { revision: string; inbounds: { tag: string; flow: string | null; supported: boolean }[] };
export const InboundFlows = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [changes, setChanges] = useState<Record<string, string | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    setBusy(true); setError("");
    try { setSettings(await fetch<Settings>("/core/inbound-flows")); setChanges({}); }
    catch (e) { setError(errorMessage(e, t("commerce.loadError"))); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const save = async () => {
    if (!settings) return;
    setBusy(true); setError("");
    try {
      setSettings(await fetch<Settings>("/core/inbound-flows", { method: "PUT", body: { revision: settings.revision, flows: changes } }));
      setChanges({}); toast({ title: t("flows.saved"), status: "success" });
    } catch (e) { setError(errorMessage(e, t("commerce.saveError"))); }
    finally { setBusy(false); }
  };
  return <VStack p={5} align="stretch" spacing={4}>
    <Text color="fg.muted">{t("flows.help")}</Text>
    {error && <Alert status="error"><AlertIcon />{error}</Alert>}
    {!settings && busy && <Spinner />}
    {settings?.inbounds.map(inbound => <HStack key={inbound.tag} justify="space-between" flexWrap="wrap">
      <Text fontWeight="medium">{inbound.tag}</Text>
      <Select aria-label={`${inbound.tag} flow`} width={{ base: "full", md: "260px" }} isDisabled={busy}
        value={(Object.prototype.hasOwnProperty.call(changes, inbound.tag) ? changes[inbound.tag] : inbound.flow) ?? "inherit"}
        onChange={e => setChanges({ ...changes, [inbound.tag]: e.target.value === "inherit" ? null : e.target.value })}>
        <option value="inherit">{t("flows.inherit")}</option>
        <option value="">{t("flows.none")}</option>
        <option value="xtls-rprx-vision" disabled={!inbound.supported}>XTLS Vision</option>
      </Select>
    </HStack>)}
    <Text fontSize="sm" color="fg.muted">{t("flows.reloadHelp")}</Text>
    <HStack><Button type="button" variant="ghost" onClick={load} isDisabled={busy}>{t("flows.reload")}</Button>
      <Button type="button" colorScheme="primary" onClick={save} isLoading={busy} isDisabled={!settings || !Object.keys(changes).length}>{t("flows.save")}</Button></HStack>
  </VStack>;
};
