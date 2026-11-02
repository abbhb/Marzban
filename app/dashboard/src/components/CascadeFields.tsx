import {
  Alert, AlertIcon, Box, Button, FormControl, FormErrorMessage,
  FormHelperText, FormLabel, Input, Select, Text, Textarea, VStack,
} from "@chakra-ui/react";
import { useEffect, useState } from "react";
import { useFormContext, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useQuery } from "react-query";
import { fetch } from "service/http";

type Entry = { id: number; name: string; source: string; type: string };
type Preview = { name: string; type: string; server: string; port: number };

export const CascadeFields = ({ path }: { path: string }) => {
  const { t } = useTranslation();
  const form = useFormContext();
  const mode = useWatch({ control: form.control, name: `${path}.cascade_mode` }) || "off";
  const entryId = useWatch({ control: form.control, name: `${path}.cascade_entry_id` });
  const yaml = useWatch({ control: form.control, name: `${path}.cascade_entry_yaml` });
  const [source, setSource] = useState(entryId ? "external" : "yaml");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => setPreview(null), [yaml]);
  const entries = useQuery(
    ["cascade-entries", query, entryId],
    ({ signal }) => fetch<Entry[]>(`/hosts/cascade-entries?search=${encodeURIComponent(query)}${entryId ? `&selected_id=${entryId}` : ""}`, { signal }),
    { enabled: mode !== "off" && source === "external", retry: false }
  );
  const entryError = form.getFieldState(`${path}.cascade_entry_id`, form.formState).error;
  const yamlError = form.getFieldState(`${path}.cascade_entry_yaml`, form.formState).error;
  const checkYaml = async () => {
    setChecking(true);
    try {
      const result = await fetch<Preview>("/hosts/cascade-preview", { method: "POST", body: { yaml } });
      if (form.getValues(`${path}.cascade_entry_yaml`) === yaml) {
        setPreview(result);
        form.clearErrors(`${path}.cascade_entry_yaml`);
      }
    } catch (error: any) {
      if (form.getValues(`${path}.cascade_entry_yaml`) === yaml) {
        form.setError(`${path}.cascade_entry_yaml`, { type: "validate", message: error?.response?.status === 400 ? "cascade.errors.cascade_invalid_yaml" : "cascade.checkError" });
      }
    } finally {
      setChecking(false);
    }
  };
  return (
    <Box w="full" borderTopWidth="1px" borderColor="border.subtle" pt={3}>
      <FormControl>
        <FormLabel htmlFor={`${path}-cascade-mode`}>{t("cascade.title")}</FormLabel>
        <Select id={`${path}-cascade-mode`} size="sm" {...form.register(`${path}.cascade_mode`)}>
          <option value="off">{t("cascade.off")}</option>
          <option value="replace">{t("cascade.replace")}</option>
          <option value="additional">{t("cascade.additional")}</option>
        </Select>
        <FormHelperText>{t("cascade.modeHelp")}</FormHelperText>
      </FormControl>
      {mode !== "off" && (
        <VStack align="stretch" spacing={3} mt={3}>
          <Alert status="info" borderRadius="md" fontSize="sm"><AlertIcon />{t("cascade.clientHelp")}</Alert>
          <FormControl>
            <FormLabel htmlFor={`${path}-cascade-source`}>{t("cascade.source")}</FormLabel>
            <Select id={`${path}-cascade-source`} size="sm" value={source} onChange={(event) => {
              setSource(event.target.value);
              form.setValue(`${path}.cascade_entry_id`, null, { shouldDirty: true });
              form.setValue(`${path}.cascade_entry_yaml`, null, { shouldDirty: true });
              form.clearErrors([`${path}.cascade_entry_id`, `${path}.cascade_entry_yaml`]);
            }}>
              <option value="yaml">{t("cascade.paste")}</option>
              <option value="external">{t("cascade.external")}</option>
            </Select>
          </FormControl>
          {source === "external" ? (
            <FormControl isInvalid={!!entryError}>
              <FormLabel htmlFor={`${path}-cascade-search`}>{t("cascade.search")}</FormLabel>
              <Input id={`${path}-cascade-search`} size="sm" value={search} onChange={(event) => setSearch(event.target.value)} />
              <FormLabel htmlFor={`${path}-cascade-entry`} mt={2}>{t("cascade.entry")}</FormLabel>
              <Select id={`${path}-cascade-entry`} size="sm" value={entryId || ""} onChange={(event) => {
                form.setValue(`${path}.cascade_entry_id`, Number(event.target.value) || null, { shouldDirty: true, shouldValidate: true });
              }}>
                <option value="">{t(entries.isFetching ? "cascade.loading" : "cascade.choose")}</option>
                {entryId && !entries.data?.some((entry) => entry.id === entryId) && <option value={entryId}>{t("cascade.unavailable", { id: entryId })}</option>}
                {entries.data?.map((entry) => <option key={entry.id} value={entry.id}>{entry.source} / {entry.name} · {entry.type}</option>)}
              </Select>
              <FormErrorMessage>{entryError && t(String(entryError.message))}</FormErrorMessage>
              {entries.isError && <Text color="red.500" role="alert" mt={2}>{t("cascade.loadError")}</Text>}
              <FormHelperText>{t("cascade.externalHelp")}</FormHelperText>
            </FormControl>
          ) : (
            <FormControl isInvalid={!!yamlError}>
              <FormLabel htmlFor={`${path}-cascade-yaml`}>{t("cascade.yaml")}</FormLabel>
              <Textarea id={`${path}-cascade-yaml`} rows={8} fontFamily="mono" fontSize="sm" spellCheck={false}
                {...form.register(`${path}.cascade_entry_yaml`)} value={yaml || ""} />
              <FormErrorMessage>{yamlError && t(String(yamlError.message))}</FormErrorMessage>
              <FormHelperText>{t("cascade.yamlHelp")}</FormHelperText>
              <Button mt={2} size="sm" onClick={checkYaml} isLoading={checking} isDisabled={!yaml?.trim()}>{t("cascade.check")}</Button>
              {preview && <Text mt={2} role="status" fontSize="sm">{t("cascade.valid", preview)}</Text>}
            </FormControl>
          )}
          <Text fontSize="sm">{t("cascade.path")}</Text>
        </VStack>
      )}
    </Box>
  );
};
