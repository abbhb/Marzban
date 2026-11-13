import { Box, Button, HStack, Select, Stack, Switch, Text } from "@chakra-ui/react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";

type Status = {
  available: boolean;
  enabled: boolean;
  verified: boolean;
  domain_strategy?: "prefer_ipv6" | null;
  list_date: string | null;
  targets?: {
    domain: string[];
    ip: string[];
    ipv4_aliases?: Record<string, string>;
  } | null;
  users: { identity: string; address: string }[];
};

export function NodeEgress({ id }: { id: number }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState("");
  const key = ["node-egress", id];
  const path = `/node-egress/${id}`;
  const query = useQuery<Status>(key, () => fetch(path), { enabled: open, retry: false });
  const update = useMutation((body: Record<string, string>) => fetch(path, { method: "POST", body, retry: 0 }), {
    onSettled: () => client.invalidateQueries(key),
  });
  const status = query.data;
  const allocation = status?.users?.find((item) => item.identity === user);
  const allDomains = status?.domain_strategy === "prefer_ipv6";
  const busy = update.isLoading || query.isFetching;
  return <Box borderTopWidth="1px" mt={4} pt={3}>
    <Button size="sm" variant="outline" aria-expanded={open} onClick={() => setOpen(!open)}>{t("nodeEgress.title")}</Button>
    {open && <Box mt={3} aria-live="polite">
      {query.isLoading && <Text>{t("loading")}</Text>}
      {(query.isError || update.isError) && <Text color="red.500">{t("nodeEgress.error")}</Text>}
      {status && (status.available ? <>
        <HStack justify="space-between" my={2}>
          <Text as="label" htmlFor={`egress-${id}`}>{t(allDomains ? "nodeEgress.preferAll" : "nodeEgress.prefer")}</Text>
          <Switch id={`egress-${id}`} isChecked={status.enabled} isDisabled={busy}
            onChange={() => update.mutate({action: status.enabled ? "off" : "on"})}/>
        </HStack>
        {!status.verified && <Text>{t("nodeEgress.pending")}</Text>}
        <Box as="details" my={3}>
          <Box as="summary" cursor="pointer" fontSize="sm" fontWeight="medium">
            {t(allDomains ? "nodeEgress.ipv4Aliases" : "nodeEgress.viewList")}
          </Box>
          <HStack my={2} wrap="wrap">
            <Text>{t(allDomains ? "nodeEgress.aliasDate" : "nodeEgress.listDate")} {status.list_date || "—"}</Text>
            <Button size="sm" isDisabled={busy || !status.enabled} onClick={() => update.mutate({action:"refresh"})}>
              {t(allDomains ? "nodeEgress.refreshAliases" : "nodeEgress.refresh")}
            </Button>
          </HStack>
          {status.targets ? (
            <Stack spacing={2} mt={2} fontSize="sm" overflowWrap="anywhere">
              {(!status.enabled || !status.verified) && <Text>{t("nodeEgress.lastApplied")}</Text>}
              {!allDomains && <Box>
                <Text fontWeight="semibold">{t("nodeEgress.domainSuffixes")} ({status.targets.domain.length})</Text>
                <Text dir="ltr" fontFamily="mono">{status.targets.domain.map(d => d.replace(/^domain:/, "")).join(", ")}</Text>
              </Box>}
              <Box>
                {!allDomains && <Text fontWeight="semibold">{t("nodeEgress.ipv4Aliases")}</Text>}
                {Object.entries(status.targets.ipv4_aliases || {}).map(([ip, host]) => (
                  <Text key={ip} dir="ltr" fontFamily="mono">{ip} → {host}</Text>
                ))}
                {!Object.keys(status.targets.ipv4_aliases || {}).length && <Text>{t("nodeEgress.noAliases")}</Text>}
              </Box>
              {!allDomains && <Box>
                <Text fontWeight="semibold">{t("nodeEgress.ipv6Prefixes")} ({status.targets.ip.length})</Text>
                <Text dir="ltr" fontFamily="mono">{status.targets.ip.join(", ")}</Text>
              </Box>}
            </Stack>
          ) : <Text mt={2} fontSize="sm">{t("nodeEgress.noList")}</Text>}
        </Box>
        <Select aria-label={t("nodeEgress.user")!} placeholder={t("nodeEgress.user")!} value={user}
          onChange={(event) => setUser(event.target.value)}>
          {status.users.map((item) => <option key={item.identity} value={item.identity}>#{item.identity} · {item.address}</option>)}
        </Select>
        <Button mt={2} size="sm" isDisabled={!allocation || busy || !status.enabled} onClick={() => {
          if (allocation && window.confirm(t("nodeEgress.confirm", { id: user, address: allocation.address })!))
            update.mutate({action:"reset", id:user, expected_address:allocation.address});
        }}>{t("nodeEgress.reset")}</Button>
      </> : <Text>{t("nodeEgress.unavailable")}</Text>)}
    </Box>}
  </Box>;
}
