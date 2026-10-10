import { Alert, AlertDescription, AlertIcon, Badge, Button, FormControl, FormHelperText, FormLabel, HStack, Spinner, Text, Textarea, useToast, VStack } from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import { errorMessage } from "service/http";

type RulesSettings = { rules: string[]; enabled: boolean; revision: number; targets: string[]; providers: string[] };

export const RulesWorkspace = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [settings, setSettings] = useState<RulesSettings | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  const apply = (value: RulesSettings) => {
    setSettings(value);
    setText(value.rules.join("\n"));
    setDirty(false);
  };
  const load = async () => {
    setBusy(true);
    setError("");
    try { apply(await fetch<RulesSettings>("/subscription/rules")); }
    catch (error) { setError(errorMessage(error, t("commerce.loadError"))); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);

  const save = async (reset = false) => {
    if (!settings || busy) return;
    setBusy(true);
    setError("");
    try {
      const rules = reset ? null : text.split("\n").map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
      apply(await fetch<RulesSettings>("/subscription/rules", { method: "PUT", body: { rules, revision: settings.revision } }));
      toast({ title: t("rules.saved"), status: "success", position: "top" });
    } catch (error) { setError(errorMessage(error, t("commerce.saveError"))); }
    finally { setBusy(false); }
  };

  return <VStack align="stretch" spacing={4} layerStyle="glass" rounded="2xl" p={{ base: 4, md: 6 }}>
    <HStack justify="space-between" flexWrap="wrap">
      <Text fontWeight="semibold">{t("rules.title")}</Text>
      {settings && <Badge colorScheme={settings.enabled ? "green" : "gray"}>{t(settings.enabled ? "rules.custom" : "rules.template")}</Badge>}
    </HStack>
    <Text color="fg.muted" fontSize="sm">{t("rules.help")}</Text>
    {error && <Alert status="error" role="alert" rounded="xl"><AlertIcon /><AlertDescription>{error}</AlertDescription></Alert>}
    {!settings && busy ? <Spinner /> : <>
      <FormControl isDisabled={!settings || busy}>
        <FormLabel htmlFor="subscription-rules">{t("rules.lines")}</FormLabel>
        <Textarea id="subscription-rules" fontFamily="mono" fontSize="sm" minH="360px" spellCheck={false} value={text} onChange={(event) => { setText(event.target.value); setDirty(true); }} placeholder="DOMAIN-SUFFIX,example.com,DIRECT&#10;MATCH,DIRECT" />
        <FormHelperText>{t("rules.targets")}: {settings?.targets.join(" · ")}</FormHelperText>
        {!!settings?.providers.length && <FormHelperText>{t("rules.providers")}: {settings.providers.join(" · ")}</FormHelperText>}
      </FormControl>
      <HStack flexWrap="wrap">
        <Button colorScheme="primary" onClick={() => void save()} isLoading={busy} isDisabled={!settings || !dirty}>{t("subscriptionSecurity.save")}</Button>
        <Button variant="outline" onClick={() => void load()} isDisabled={busy}>{t("rules.reload")}</Button>
        <Button variant="ghost" onClick={() => { setText(""); setDirty(true); }} isDisabled={busy || !settings?.enabled}>{t("rules.prepareReset")}</Button>
      </HStack>
      {settings?.enabled && dirty && !text.trim() && <Button alignSelf="start" variant="outline" onClick={() => void save(true)} isDisabled={busy}>{t("rules.confirmReset")}</Button>}
    </>}
  </VStack>;
};
