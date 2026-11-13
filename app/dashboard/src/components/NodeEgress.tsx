import { Box, Button, HStack, Select, Switch, Text } from "@chakra-ui/react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";

type Status = {
  available: boolean;
  enabled: boolean;
  verified: boolean;
  list_date: string | null;
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
  const busy = update.isLoading || query.isFetching;
  return <Box borderTopWidth="1px" mt={4} pt={3}>
    <Button size="sm" variant="outline" aria-expanded={open} onClick={() => setOpen(!open)}>{t("nodeEgress.title")}</Button>
    {open && <Box mt={3} aria-live="polite">
      {query.isLoading && <Text>{t("loading")}</Text>}
      {(query.isError || update.isError) && <Text color="red.500">{t("nodeEgress.error")}</Text>}
      {status && (status.available ? <>
        <HStack justify="space-between" my={2}>
          <Text as="label" htmlFor={`egress-${id}`}>{t("nodeEgress.prefer")}</Text>
          <Switch id={`egress-${id}`} isChecked={status.enabled} isDisabled={busy}
            onChange={() => update.mutate({action: status.enabled ? "off" : "on"})}/>
        </HStack>
        {!status.verified && <Text>{t("nodeEgress.pending")}</Text>}
        <HStack my={2} wrap="wrap">
          <Text>{t("nodeEgress.listDate")} {status.list_date || "—"}</Text>
          <Button size="sm" isDisabled={busy || !status.enabled} onClick={() => update.mutate({action:"refresh"})}>{t("nodeEgress.refresh")}</Button>
        </HStack>
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
