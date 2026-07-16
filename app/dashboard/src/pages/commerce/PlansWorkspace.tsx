import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  Checkbox,
  FormControl,
  FormLabel,
  Heading,
  HStack,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  Spinner,
  Text,
  Textarea,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import { DataWorkspace } from "components/DataWorkspace";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "react-query";
import { fetch } from "service/http";
import { SubscriptionPlan } from "types/Commerce";
import { formatBytes } from "utils/formatByte";
import { money } from "./shared";

type Inbound = { tag: string; protocol: string };
type Draft = {
  name: string;
  description: string;
  price: string;
  durationDays: string;
  dataLimitGb: string;
  inboundTags: string[];
  isVisible: boolean;
};

const emptyDraft: Draft = {
  name: "",
  description: "",
  price: "",
  durationDays: "30",
  dataLimitGb: "100",
  inboundTags: [],
  isVisible: true,
};

export const PlansWorkspace = ({ onReady }: { onReady?: () => void }) => {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const modal = useDisclosure();
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const plansQuery = useQuery(
    ["commerce", "plans"],
    ({ signal }) =>
      fetch<SubscriptionPlan[]>("/commerce/admin/plans", {
        timeout: 15000,
        signal,
      }),
    { retry: false }
  );
  const inboundsQuery = useQuery(
    ["commerce", "inbounds"],
    ({ signal }) =>
      fetch<Record<string, Inbound[]>>("/inbounds", {
        timeout: 15000,
        signal,
      }),
    { retry: false }
  );
  const plans = plansQuery.data || [];
  const inbounds = Object.values(inboundsQuery.data || {})
    .flat()
    .filter((item) => item.protocol === "vless");

  useEffect(() => {
    if (!plansQuery.isLoading && !inboundsQuery.isLoading) onReady?.();
  }, [inboundsQuery.isLoading, onReady, plansQuery.isLoading]);

  const closeEditor = () => {
    modal.onClose();
    setEditingId(null);
    setDraft(emptyDraft);
  };

  const create = () => {
    setEditingId(null);
    setDraft(emptyDraft);
    modal.onOpen();
  };

  const edit = (plan: SubscriptionPlan) => {
    setEditingId(plan.id);
    setDraft({
      name: plan.name,
      description: plan.description,
      price: (plan.price_minor / 100).toFixed(2),
      durationDays: String(plan.duration_days),
      dataLimitGb: String(plan.data_limit / 1024 ** 3),
      inboundTags: plan.inbound_tags,
      isVisible: plan.is_visible,
    });
    modal.onOpen();
  };

  const save = async () => {
    const priceMinor = Math.round(Number(draft.price) * 100);
    const durationDays = Number(draft.durationDays);
    const dataLimit = Math.round(Number(draft.dataLimitGb) * 1024 ** 3);
    if (
      !draft.name.trim() ||
      !Number.isFinite(priceMinor) ||
      !Number.isFinite(durationDays) ||
      !Number.isFinite(dataLimit) ||
      !draft.inboundTags.length
    ) {
      toast({
        title: t("commerce.invalidPlan"),
        status: "error",
        position: "top",
      });
      return;
    }
    setSaving(true);
    try {
      await fetch(
        editingId
          ? `/commerce/admin/plans/${editingId}`
          : "/commerce/admin/plans",
        {
          method: editingId ? "PUT" : "POST",
          body: {
            name: draft.name,
            description: draft.description,
            price_minor: priceMinor,
            currency: "CNY",
            duration_days: durationDays,
            data_limit: dataLimit,
            inbound_tags: draft.inboundTags,
            is_visible: draft.isVisible,
          },
        }
      );
      await queryClient.invalidateQueries(["commerce", "plans"]);
      await queryClient.invalidateQueries(["commerce", "accounts"]);
      toast({
        title: t("commerce.planSaved"),
        status: "success",
        position: "top",
      });
      closeEditor();
    } catch (error: any) {
      toast({
        title: error?.data?.detail || t("commerce.saveError"),
        status: "error",
        position: "top",
      });
    } finally {
      setSaving(false);
    }
  };

  if (plansQuery.isLoading || inboundsQuery.isLoading) {
    return (
      <VStack py="20">
        <Spinner color="primary.500" />
      </VStack>
    );
  }

  if (plansQuery.isError || inboundsQuery.isError) {
    return (
      <Alert status="error" rounded="2xl" alignItems="center">
        <AlertIcon />
        <AlertDescription flex="1">
          {t("portal.requestFailed")}
        </AlertDescription>
        <Button
          size="sm"
          variant="outline"
          colorScheme="red"
          onClick={() => {
            void plansQuery.refetch();
            void inboundsQuery.refetch();
          }}
        >
          {t("portal.retry")}
        </Button>
      </Alert>
    );
  }

  return (
    <>
      <DataWorkspace
        title={t("commerce.plans")}
        description={t("commerce.plansWorkspaceHelp")}
        total={plans.length}
        toolbar={
          <Button colorScheme="primary" size="sm" onClick={create}>
            {t("commerce.createPlan")}
          </Button>
        }
        isEmpty={!plans.length}
        emptyTitle={t("commerce.noPlans")}
      >
        <SimpleGrid
          columns={{ base: 1, md: 2, xl: 4 }}
          spacing="4"
          px={{ base: 4, md: 6 }}
          pb="6"
        >
          {plans.map((plan) => (
            <Card key={plan.id} rounded="2xl">
              <CardBody>
                <HStack justify="space-between" align="start">
                  <Box minW="0">
                    <HStack>
                      <Heading size="sm" noOfLines={1}>
                        {plan.name}
                      </Heading>
                      {!plan.is_visible && (
                        <Badge>{t("commerce.hidden")}</Badge>
                      )}
                    </HStack>
                    <Text mt="2" color="fg.muted" fontSize="sm" noOfLines={2}>
                      {plan.description || t("portal.planDefaultDescription")}
                    </Text>
                    <Text mt="4" fontWeight="750">
                      {money(plan.price_minor)} · {plan.duration_days}{" "}
                      {t("portal.days")}
                    </Text>
                    <Text mt="1" fontSize="sm" color="fg.muted">
                      {plan.data_limit
                        ? formatBytes(plan.data_limit)
                        : t("portal.unlimited")}
                    </Text>
                    <Text mt="3" fontSize="xs" color="fg.subtle" noOfLines={1}>
                      {plan.inbound_tags.join(" · ")}
                    </Text>
                  </Box>
                  <Button size="sm" variant="ghost" onClick={() => edit(plan)}>
                    {t("commerce.edit")}
                  </Button>
                </HStack>
              </CardBody>
            </Card>
          ))}
        </SimpleGrid>
      </DataWorkspace>

      <Modal
        isOpen={modal.isOpen}
        onClose={closeEditor}
        size="4xl"
        scrollBehavior="inside"
        isCentered
      >
        <ModalOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <ModalContent layerStyle="glass-strong" rounded="3xl" mx="4">
          <ModalHeader>
            {editingId ? t("commerce.editPlan") : t("commerce.createPlan")}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing="4">
              <FormControl>
                <FormLabel>{t("commerce.planName")}</FormLabel>
                <Input
                  value={draft.name}
                  onChange={(event) =>
                    setDraft({ ...draft, name: event.target.value })
                  }
                />
              </FormControl>
              <FormControl>
                <FormLabel>{t("commerce.priceCny")}</FormLabel>
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={draft.price}
                  onChange={(event) =>
                    setDraft({ ...draft, price: event.target.value })
                  }
                />
              </FormControl>
              <FormControl>
                <FormLabel>{t("commerce.durationDays")}</FormLabel>
                <Input
                  type="number"
                  min="1"
                  value={draft.durationDays}
                  onChange={(event) =>
                    setDraft({ ...draft, durationDays: event.target.value })
                  }
                />
              </FormControl>
              <FormControl>
                <FormLabel>{t("commerce.dataLimitGb")}</FormLabel>
                <Input
                  type="number"
                  min="0"
                  value={draft.dataLimitGb}
                  onChange={(event) =>
                    setDraft({ ...draft, dataLimitGb: event.target.value })
                  }
                />
              </FormControl>
              <FormControl gridColumn={{ md: "1 / -1" }}>
                <FormLabel>{t("commerce.description")}</FormLabel>
                <Textarea
                  value={draft.description}
                  onChange={(event) =>
                    setDraft({ ...draft, description: event.target.value })
                  }
                />
              </FormControl>
              <FormControl gridColumn={{ md: "1 / -1" }}>
                <FormLabel>{t("commerce.allowedNodes")}</FormLabel>
                <SimpleGrid
                  columns={{ base: 1, md: 2 }}
                  spacing="2"
                  maxH="240px"
                  overflowY="auto"
                  p="3"
                  layerStyle="glassSubtle"
                  rounded="xl"
                >
                  {inbounds.map((inbound) => (
                    <Checkbox
                      key={inbound.tag}
                      isChecked={draft.inboundTags.includes(inbound.tag)}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          inboundTags: event.target.checked
                            ? [...draft.inboundTags, inbound.tag]
                            : draft.inboundTags.filter(
                                (tag) => tag !== inbound.tag
                              ),
                        })
                      }
                    >
                      {inbound.tag}
                    </Checkbox>
                  ))}
                </SimpleGrid>
              </FormControl>
              <Checkbox
                isChecked={draft.isVisible}
                onChange={(event) =>
                  setDraft({ ...draft, isVisible: event.target.checked })
                }
              >
                {t("commerce.visibleToUsers")}
              </Checkbox>
            </SimpleGrid>
          </ModalBody>
          <ModalFooter gap="3">
            <Button variant="ghost" onClick={closeEditor}>
              {t("cancel")}
            </Button>
            <Button colorScheme="primary" onClick={save} isLoading={saving}>
              {t("commerce.savePlan")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
};
