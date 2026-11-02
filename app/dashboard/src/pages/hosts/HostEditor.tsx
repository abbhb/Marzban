import {
  Box, Checkbox, FormControl, FormErrorMessage, FormHelperText, FormLabel,
  Input, Select, SimpleGrid, Switch, Text, VStack,
} from "@chakra-ui/react";
import { CascadeFields } from "components/CascadeFields";
import { proxyALPN, proxyFingerprint, proxyHostSecurity } from "constants/Proxies";
import { Controller, useFormContext } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Category, Host, HostForm, Inbound } from "./schema";

export const HostEditor = ({ index, category, inbound }: { index: number; category: Category; inbound?: Inbound }) => {
  const form = useFormContext<HostForm>();
  const { t } = useTranslation();
  const path = `routes.${index}.value` as const;
  const error = (field: keyof Host) => form.formState.errors.routes?.[index]?.value?.[field]?.message;
  const textField = (field: "remark" | "address" | "port" | "sni" | "host" | "path" | "fragment_setting" | "noise_setting", label: string, help?: string) => (
    <FormControl isInvalid={!!error(field)} isRequired={field === "remark" || field === "address"}>
      <FormLabel htmlFor={`host-${field}`}>{label}</FormLabel>
      <Input id={`host-${field}`} autoComplete="off" type={field === "port" ? "number" : "text"}
        min={field === "port" ? 1 : undefined} max={field === "port" ? 65535 : undefined}
        placeholder={!["remark", "address", "fragment_setting", "noise_setting"].includes(field) ? t("hostsPage.inherit") : undefined}
        {...form.register(`${path}.${field}`, { setValueAs: value => field === "port" ? (value === "" || value == null ? null : Number(value))
          : field !== "remark" && field !== "address" && value === "" ? null : value })} />
      {help && <FormHelperText>{help}</FormHelperText>}
      <FormErrorMessage>{error(field) && t(String(error(field)))}</FormErrorMessage>
    </FormControl>
  );
  const toggle = (field: "allowinsecure" | "use_sni_as_host" | "mux_enable" | "random_user_agent", label: string, help: string) => (
    <FormControl>
      <Controller control={form.control} name={`${path}.${field}`} render={({ field: input }) => (
        <Checkbox id={`host-${field}`} isChecked={!!input.value} onChange={event => input.onChange(event.target.checked)} onBlur={input.onBlur} ref={input.ref}>{label}</Checkbox>
      )} />
      <FormHelperText>{help}</FormHelperText>
    </FormControl>
  );
  const selectField = (field: "security" | "alpn" | "fingerprint", options: { title: string; value: string }[]) => (
    <FormControl><FormLabel htmlFor={`host-${field}`}>{t(`hostsDialog.${field}`)}</FormLabel>
      <Select id={`host-${field}`} {...form.register(`${path}.${field}`)}>
        {options.map(option => <option key={option.value} value={option.value}>{option.value === "inbound_default" || option.value === "" ? t("hostsPage.inherit") : option.title}</option>)}
      </Select>
    </FormControl>
  );
  return <VStack align="stretch" spacing={6}>
    <Text color="fg.muted" fontSize="sm">{t(`hostsPage.${category}Help`)}</Text>
    {category === "basic" && <>
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={5}>
        {textField("remark", t("hostsPage.routeName"), t("hostsPage.nameHelp"))}
        <FormControl><FormLabel htmlFor="host-enabled">{t("hostsPage.availability")}</FormLabel>
          <Controller control={form.control} name={`${path}.is_disabled`} render={({ field }) => (
            <Switch id="host-enabled" colorScheme="primary" isChecked={!field.value} onChange={event => field.onChange(!event.target.checked)} onBlur={field.onBlur} ref={field.ref}>{t("hostsPage.enabled")}</Switch>
          )} />
          <FormHelperText>{t("hostsPage.enabledHelp")}</FormHelperText>
        </FormControl>
        {textField("address", t("hostsPage.address"))}
        {textField("port", t("hostsPage.port"), t("hostsPage.portHelp", { port: inbound?.port ?? "—" }))}
      </SimpleGrid>
      <Box as="details" fontSize="sm" color="fg.muted"><Box as="summary" cursor="pointer">{t("hostsPage.variables")}</Box>
        <Text mt={2}>{t("hostsPage.variablesHelp")}</Text>
      </Box>
    </>}
    {category === "connection" && <>
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={5}>
        {textField("sni", "SNI", t("hostsPage.sniHelp"))}
        {textField("host", "HTTP Host", t("hostsPage.hostHelp"))}
        {textField("path", t("hostsPage.path"), t("hostsPage.pathHelp"))}
        {selectField("security", proxyHostSecurity)}
        {selectField("alpn", proxyALPN)}
        {selectField("fingerprint", proxyFingerprint)}
      </SimpleGrid>
      {toggle("use_sni_as_host", t("hostsPage.useSni"), t("hostsPage.useSniHelp"))}
      {toggle("allowinsecure", t("hostsDialog.allowinsecure"), t("hostsPage.insecureHelp"))}
    </>}
    {category === "cascade" && <CascadeFields path={path} />}
    {category === "advanced" && <>
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={5}>
        {textField("fragment_setting", t("hostsDialog.fragment"), "10-100,100-200,tlshello")}
        {textField("noise_setting", t("hostsDialog.noise"), "rand:10-20,100-200")}
      </SimpleGrid>
      {toggle("mux_enable", t("hostsDialog.muxEnable"), t("hostsPage.muxHelp"))}
      {toggle("random_user_agent", t("hostsDialog.randomUserAgent"), t("hostsPage.randomHelp"))}
    </>}
  </VStack>;
};
