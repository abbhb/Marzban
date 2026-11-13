import {
  Alert, AlertIcon, Box, Button, Checkbox, Code, FormControl, FormErrorMessage,
  FormLabel, HStack, Input, Switch, Text, VStack, useToast,
} from "@chakra-ui/react";
import { zodResolver } from "@hookform/resolvers/zod";
import { NodeSchema, NodeType, getNodeDefaultValues, useNodes } from "contexts/NodesContext";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useNavigate } from "react-router-dom";
import { errorMessage, fetch } from "service/http";
import { ServiceNode } from "./types";

export const NodeSettings = ({ node, onDirty, onSaving }: {
  node?: ServiceNode;
  onDirty: (dirty: boolean) => void;
  onSaving: (saving: boolean) => void;
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();
  const queries = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");
  const [certificateUrl, setCertificateUrl] = useState("");
  const [showCertificate, setShowCertificate] = useState(false);
  const form = useForm<NodeType>({ resolver: zodResolver(NodeSchema), defaultValues: node || { ...getNodeDefaultValues(), add_as_new_host: false } });
  const settings = useQuery(["node-settings"], () => fetch<{ certificate: string }>("/node/settings"), { enabled: node?.id !== 0, refetchOnWindowFocus: false });
  useEffect(() => {
    if (!settings.data?.certificate) return;
    const url = URL.createObjectURL(new Blob([settings.data.certificate], { type: "text/plain" }));
    setCertificateUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [settings.data?.certificate]);
  useEffect(() => { onDirty(form.formState.isDirty); }, [form.formState.isDirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);
  const save = useMutation(async (values: NodeType) => node ? useNodes.getState().updateNode(values) : useNodes.getState().addNode(values), {
    onMutate: () => { setError(""); onSaving(true); },
    onSuccess: async result => {
      const saved = result as ServiceNode;
      form.reset(saved); onDirty(false);
      await queries.invalidateQueries("node-services");
      toast({ title: t(node ? "nodeServices.saved" : "nodes.addNodeSuccess", { name: saved.name }), status: "success", isClosable: true });
      if (!node) { onSaving(false); navigate(`/nodes/${saved.id}?tab=settings`, { replace: true }); }
    },
    onError: error => setError(errorMessage(error, t("nodeServices.saveError"))),
    onSettled: () => onSaving(false),
  });
  const remove = useMutation(() => fetch(`/node/${node!.id}`, { method: "DELETE", retry: 0 }), {
    onMutate: () => { setError(""); onSaving(true); },
    onSuccess: async () => {
      form.reset(form.getValues()); onDirty(false); onSaving(false);
      await queries.invalidateQueries("node-services");
      navigate("/nodes", { replace: true });
    },
    onError: error => setError(errorMessage(error, t("nodeServices.saveError"))),
    onSettled: () => onSaving(false),
  });
  if (node?.id === 0) return <Alert status="info" borderRadius="xl"><AlertIcon />{t("nodeServices.localSettings")}</Alert>;
  const disabled = save.isLoading || remove.isLoading;
  return <Box maxW="760px">
    {error && <Alert status="error" borderRadius="xl" mb={4}><AlertIcon /><Text overflowWrap="anywhere">{error}</Text></Alert>}
    <form onSubmit={form.handleSubmit(values => save.mutate(values))}>
      <VStack as="fieldset" disabled={disabled} border="0" m="0" p="0" align="stretch" spacing={5}>
        {(["name", "address", "port", "api_port", "usage_coefficient"] as const).map(field => <FormControl key={field} isInvalid={!!form.formState.errors[field]}>
          <FormLabel htmlFor={`node-${field}`}>{t(`nodeServices.fields.${field}`)}</FormLabel>
          <Input id={`node-${field}`} {...form.register(field)} type={["port", "api_port", "usage_coefficient"].includes(field) ? "number" : "text"}
            min={field === "usage_coefficient" ? "0.01" : "1"} max={field.endsWith("port") ? "65535" : undefined}
            step={field === "usage_coefficient" ? "any" : undefined} />
          <FormErrorMessage>{form.formState.errors[field]?.message}</FormErrorMessage>
        </FormControl>)}
        {node ? <FormControl display="flex" alignItems="center" gap={3}><FormLabel htmlFor="node-enabled" mb={0}>{t("nodeServices.enabled")}</FormLabel>
          <Switch id="node-enabled" colorScheme="primary" isChecked={form.watch("status") !== "disabled"} onChange={event => form.setValue("status", event.target.checked ? "connecting" : "disabled", { shouldDirty: true })} /></FormControl>
          : <Checkbox {...form.register("add_as_new_host")}>{t("nodes.addHostForEveryInbound")}</Checkbox>}
        <HStack><Button colorScheme="primary" type="submit" isLoading={save.isLoading} isDisabled={!!node && !form.formState.isDirty}>{t(node ? "nodes.editNode" : "nodes.addNode")}</Button>
          {node && <Text color="fg.muted" fontSize="sm">{t("nodeServices.saveHelp")}</Text>}</HStack>
      </VStack>
    </form>
    <Box mt={7} borderTopWidth="1px" borderColor="border.subtle" pt={5}>
      <Text fontSize="sm" color="fg.muted" mb={3}>{t("nodes.connection-hint")}</Text>
      {settings.isError && <Button variant="outline" onClick={() => settings.refetch()}>{t("nodeServices.certificateRetry")}</Button>}
      {certificateUrl && <HStack flexWrap="wrap"><Button as="a" size="sm" href={certificateUrl} download="ssl_client_cert.pem">{t("nodes.download-certificate")}</Button>
        <Button size="sm" variant="ghost" onClick={() => setShowCertificate(value => !value)}>{t(showCertificate ? "nodes.hide-certificate" : "nodes.show-certificate")}</Button></HStack>}
      {showCertificate && <Code display="block" whiteSpace="pre-wrap" overflowWrap="anywhere" p={3} mt={3}>{settings.data?.certificate}</Code>}
    </Box>
    {node && <Box mt={8} borderTopWidth="1px" borderColor="border.subtle" pt={5}>
      {!confirmDelete ? <Button colorScheme="red" variant="outline" onClick={() => setConfirmDelete(true)} isDisabled={disabled}>{t("nodeServices.delete")}</Button>
        : <Alert status="warning" borderRadius="xl" alignItems="start"><AlertIcon /><Box><Text>{t("nodeServices.deleteHelp", { name: node.name })}</Text>
          <HStack mt={3}><Button size="sm" onClick={() => setConfirmDelete(false)} isDisabled={disabled}>{t("cancel")}</Button>
            <Button size="sm" colorScheme="red" isLoading={remove.isLoading} onClick={() => remove.mutate()}>{t("delete")}</Button></HStack></Box></Alert>}
    </Box>}
  </Box>;
};
