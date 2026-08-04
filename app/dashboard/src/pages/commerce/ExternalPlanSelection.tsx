import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Collapse,
  HStack,
  Icon,
  IconButton,
  Spinner,
  Text,
  VStack,
} from "@chakra-ui/react";
import { ChevronDownIcon, ChevronUpIcon } from "@heroicons/react/24/outline";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "react-query";
import { fetch } from "service/http";
import {
  ExternalSubscriptionNode,
  ExternalSubscriptionSource,
  PageResult,
  PlanExternalSelection,
} from "types/Commerce";
import { PaginationControls } from "components/DataWorkspace";
import { WorkspaceSearch, initialPageState, pageUrl, useDebouncedValue } from "./shared";

type ExternalPlanSelectionProps = {
  isActive: boolean;
  value: PlanExternalSelection[];
  onChange: (value: PlanExternalSelection[]) => void;
};

type SourceRowProps = {
  source: ExternalSubscriptionSource;
  selection?: PlanExternalSelection;
  onSelectionChange: (selection?: PlanExternalSelection) => void;
};

const ExternalNodePicker = ({
  source,
  selection,
  onChange,
  isOpen,
}: {
  source: ExternalSubscriptionSource;
  selection: PlanExternalSelection;
  onChange: (selection: PlanExternalSelection) => void;
  isOpen: boolean;
}) => {
  const { t } = useTranslation();
  const [state, setState] = useState(initialPageState);
  const search = useDebouncedValue(state.search);
  const nodesQuery = useQuery(
    [
      "commerce",
      "external-subscription-nodes",
      source.id,
      state.page,
      state.pageSize,
      search,
    ],
    ({ signal }) =>
      fetch<PageResult<ExternalSubscriptionNode>>(
        pageUrl(
          `/commerce/admin/external-subscriptions/${source.id}/nodes`,
          { ...state, search }
        ),
        { timeout: 15000, signal }
      ),
    { enabled: isOpen, keepPreviousData: true, retry: false }
  );
  const selectedIds = [...selection.node_ids].sort((left, right) => left - right);
  const selectedNodesQuery = useQuery(
    [
      "commerce",
      "external-subscription-selected-nodes",
      source.id,
      selectedIds.join(","),
    ],
    async ({ signal }) => {
      if (!selectedIds.length) return [] as ExternalSubscriptionNode[];
      const base = `/commerce/admin/external-subscriptions/${source.id}/nodes`;
      const pageSize = 100;
      const idChunks = Array.from(
        { length: Math.ceil(selectedIds.length / pageSize) },
        (_, index) => selectedIds.slice(index * pageSize, (index + 1) * pageSize)
      );
      const loadChunk = (nodeIds: number[]) => {
        const params = new URLSearchParams({
          page: "1",
          page_size: String(pageSize),
          ids: nodeIds.join(","),
        });
        return fetch<PageResult<ExternalSubscriptionNode>>(
          `${base}?${params.toString()}`,
          { timeout: 15000, signal }
        );
      };
      const pages = await Promise.all(idChunks.map(loadChunk));
      return pages.flatMap((page) => page.items);
    },
    {
      enabled: isOpen && selectedIds.length > 0,
      retry: false,
      keepPreviousData: true,
    }
  );
  const pageNodes = nodesQuery.data?.items || [];
  const selected = new Set(selection.node_ids);
  const activePageNodes = pageNodes.filter((node) => node.is_active);
  const allPageSelected =
    activePageNodes.length > 0 &&
    activePageNodes.every((node) => selected.has(node.id));
  const inactiveSelectedIds = (selectedNodesQuery.data || [])
    .filter((node) => !node.is_active)
    .map((node) => node.id);
  const inactiveSelectedCount = inactiveSelectedIds.length;

  const toggleNode = (nodeId: number, checked: boolean) => {
    const nodeIds = checked
      ? Array.from(new Set([...selection.node_ids, nodeId]))
      : selection.node_ids.filter((id) => id !== nodeId);
    onChange({ ...selection, node_ids: nodeIds });
  };

  const togglePage = () => {
    const pageIds = activePageNodes.map((node) => node.id);
    const nodeIds = allPageSelected
      ? selection.node_ids.filter((id) => !pageIds.includes(id))
      : Array.from(new Set([...selection.node_ids, ...pageIds]));
    onChange({ ...selection, node_ids: nodeIds });
  };

  return (
    <VStack align="stretch" spacing="3" mt="3" ps={{ base: 0, md: 7 }}>
      <HStack align="center" justify="space-between" flexWrap="wrap" gap="2">
        <WorkspaceSearch
          state={state}
          setState={setState}
          isLoading={nodesQuery.isFetching}
          placeholder={t("commerce.externalSearchNodes")}
        />
        <HStack>
          <Text fontSize="xs" color="fg.muted">
            {t("commerce.externalSelectedCount", {
              count: selection.node_ids.length,
            })}
          </Text>
          {selectedNodesQuery.isFetching && <Spinner size="xs" />}
          <Button
            size="xs"
            variant="ghost"
            onClick={togglePage}
            isDisabled={!activePageNodes.length}
          >
            {allPageSelected
              ? t("commerce.externalClearPage")
              : t("commerce.externalSelectPage")}
          </Button>
        </HStack>
      </HStack>

      {inactiveSelectedCount > 0 && (
        <Alert status="warning" rounded="xl" py="2" gap="2">
          <AlertIcon />
          <AlertDescription fontSize="xs" flex="1">
            {t("commerce.externalInactiveSelected", {
              count: inactiveSelectedCount,
            })}
          </AlertDescription>
          <Button
            size="xs"
            variant="ghost"
            colorScheme="orange"
            flexShrink={0}
            onClick={() =>
              onChange({
                ...selection,
                node_ids: selection.node_ids.filter(
                  (nodeId) => !inactiveSelectedIds.includes(nodeId)
                ),
              })
            }
          >
            {t("commerce.externalRemoveInactive")}
          </Button>
        </Alert>
      )}

      {nodesQuery.isError ? (
        <Alert status="error" rounded="xl">
          <AlertIcon />
          <AlertDescription>{t("commerce.externalNodesLoadError")}</AlertDescription>
        </Alert>
      ) : nodesQuery.isLoading ? (
        <HStack justify="center" py="8">
          <Spinner size="sm" color="primary.500" />
        </HStack>
      ) : (
        <VStack align="stretch" spacing="1">
          {pageNodes.map((node) => (
            <Checkbox
              key={node.id}
              minH="10"
              px="3"
              py="2"
              rounded="xl"
              bg="surface.input"
              isChecked={selected.has(node.id)}
              isDisabled={!node.is_active && !selected.has(node.id)}
              onChange={(event) => toggleNode(node.id, event.target.checked)}
            >
              <HStack minW="0" spacing="2">
                <Text fontSize="sm" noOfLines={1}>
                  {node.name}
                </Text>
                <Badge flexShrink={0}>{node.proxy_type}</Badge>
                {!node.is_active && (
                  <Badge flexShrink={0} colorScheme="orange">
                    {t("commerce.externalNodeMissing")}
                  </Badge>
                )}
              </HStack>
            </Checkbox>
          ))}
          {!pageNodes.length && (
            <Text py="8" textAlign="center" color="fg.muted" fontSize="sm">
              {t("commerce.externalNoNodes")}
            </Text>
          )}
        </VStack>
      )}

      {nodesQuery.data && (
        <PaginationControls
          page={state.page}
          pageSize={state.pageSize}
          total={nodesQuery.data.total}
          onPageChange={(page) => setState((value) => ({ ...value, page }))}
          onPageSizeChange={(pageSize) =>
            setState((value) => ({ ...value, pageSize, page: 1 }))
          }
        />
      )}
    </VStack>
  );
};

const SourceRow = ({ source, selection, onSelectionChange }: SourceRowProps) => {
  const { t } = useTranslation();
  const [isOpen, setOpen] = useState(false);
  const isSelected = Boolean(selection);
  const isPartial = selection?.mode === "selected";

  const setMode = (mode: "all" | "selected") => {
    onSelectionChange({
      source_id: source.id,
      mode,
      node_ids: mode === "selected" ? selection?.node_ids || [] : [],
    });
    if (mode === "selected") setOpen(true);
  };

  return (
    <Box rounded="2xl" bg="surface.input" px={{ base: 3, md: 4 }} py="3">
      <HStack align="start" justify="space-between" gap="3">
        <Checkbox
          mt="1"
          minW="0"
          flex="1"
          isChecked={isSelected}
          isIndeterminate={isPartial}
          isDisabled={!source.enabled && !isSelected}
          onChange={(event) =>
            onSelectionChange(
              event.target.checked
                ? { source_id: source.id, mode: "all", node_ids: [] }
                : undefined
            )
          }
        >
          <Box minW="0">
            <Text fontWeight="700" noOfLines={1}>
              {source.name}
            </Text>
            <HStack mt="1" spacing="2" flexWrap="wrap">
              <Text fontSize="xs" color="fg.muted" noOfLines={1}>
                {source.group_name}
              </Text>
              <Badge>{t("commerce.externalNodeCount", { count: source.node_count })}</Badge>
              {!source.enabled && (
                <Badge colorScheme="gray">{t("commerce.externalStatus.disabled")}</Badge>
              )}
            </HStack>
          </Box>
        </Checkbox>
        <IconButton
          aria-label={
            isOpen ? t("commerce.externalCollapse") : t("commerce.externalExpand")
          }
          icon={<Icon as={isOpen ? ChevronUpIcon : ChevronDownIcon} boxSize="4" />}
          size="sm"
          variant="ghost"
          onClick={() => setOpen((value) => !value)}
        />
      </HStack>

      {selection && (
        <HStack mt="3" ps={{ base: 0, md: 7 }} spacing="2" flexWrap="wrap">
          <Button
            size="xs"
            variant={selection.mode === "all" ? "solid" : "ghost"}
            colorScheme={selection.mode === "all" ? "primary" : undefined}
            onClick={() => setMode("all")}
          >
            {t("commerce.externalAllNodes")}
          </Button>
          <Button
            size="xs"
            variant={selection.mode === "selected" ? "solid" : "ghost"}
            colorScheme={selection.mode === "selected" ? "primary" : undefined}
            onClick={() => setMode("selected")}
          >
            {t("commerce.externalSelectedNodes")}
          </Button>
          <Text fontSize="xs" color="fg.muted">
            {selection.mode === "all"
              ? t("commerce.externalAllNodesHelp")
              : t("commerce.externalSelectedCount", {
                  count: selection.node_ids.length,
                })}
          </Text>
        </HStack>
      )}

      <Collapse in={isOpen && Boolean(selection)} animateOpacity>
        {selection?.mode === "selected" ? (
          <ExternalNodePicker
            source={source}
            selection={selection}
            onChange={(value) => onSelectionChange(value)}
            isOpen={isOpen}
          />
        ) : (
          <Text mt="3" ps={{ base: 0, md: 7 }} fontSize="sm" color="fg.muted">
            {t("commerce.externalAllNodesHelp")}
          </Text>
        )}
      </Collapse>
    </Box>
  );
};

export const ExternalPlanSelection = ({
  isActive,
  value,
  onChange,
}: ExternalPlanSelectionProps) => {
  const { t } = useTranslation();
  const [sourceState, setSourceState] = useState(initialPageState);
  const sourcesQuery = useQuery(
    ["commerce", "external-subscriptions"],
    ({ signal }) =>
      fetch<ExternalSubscriptionSource[]>(
        "/commerce/admin/external-subscriptions",
        { timeout: 15000, signal }
      ),
    { enabled: isActive, retry: false }
  );

  if (!isActive) return null;
  if (sourcesQuery.isLoading) {
    return (
      <HStack justify="center" py="8">
        <Spinner size="sm" color="primary.500" />
      </HStack>
    );
  }
  if (sourcesQuery.isError) {
    return (
      <Alert status="error" rounded="xl">
        <AlertIcon />
        <AlertDescription flex="1">
          {t("commerce.externalLoadError")}
        </AlertDescription>
        <Button size="xs" variant="ghost" onClick={() => sourcesQuery.refetch()}>
          {t("portal.retry")}
        </Button>
      </Alert>
    );
  }

  const sources = sourcesQuery.data || [];
  if (!sources.length) {
    return (
      <Text py="6" textAlign="center" color="fg.muted" fontSize="sm">
        {t("commerce.externalPlanEmpty")}
      </Text>
    );
  }

  const updateSource = (
    sourceId: number,
    selection?: PlanExternalSelection
  ) => {
    const next = value.filter((item) => item.source_id !== sourceId);
    if (selection) next.push(selection);
    onChange(next);
  };

  const normalizedSearch = sourceState.search.trim().toLocaleLowerCase();
  const filteredSources = normalizedSearch
    ? sources.filter((source) =>
        [source.name, source.group_name, source.status].some((value) =>
          value.toLocaleLowerCase().includes(normalizedSearch)
        )
      )
    : sources;
  const sourcePageCount = Math.max(
    1,
    Math.ceil(filteredSources.length / sourceState.pageSize)
  );
  const safeSourcePage = Math.min(sourceState.page, sourcePageCount);
  const visibleSources = filteredSources.slice(
    (safeSourcePage - 1) * sourceState.pageSize,
    safeSourcePage * sourceState.pageSize
  );

  return (
    <VStack align="stretch" spacing="2">
      <WorkspaceSearch
        state={sourceState}
        setState={setSourceState}
        placeholder={t("commerce.externalSearchSources")}
      />
      {visibleSources.map((source) => (
        <SourceRow
          key={source.id}
          source={source}
          selection={value.find((item) => item.source_id === source.id)}
          onSelectionChange={(selection) => updateSource(source.id, selection)}
        />
      ))}
      {!visibleSources.length && (
        <Text py="6" textAlign="center" color="fg.muted" fontSize="sm">
          {t("commerce.externalNoSourcesMatch")}
        </Text>
      )}
      {!!filteredSources.length && (
        <PaginationControls
          page={safeSourcePage}
          pageSize={sourceState.pageSize}
          total={filteredSources.length}
          pageSizeOptions={[10, 20, 50]}
          onPageChange={(page) =>
            setSourceState((value) => ({ ...value, page }))
          }
          onPageSizeChange={(pageSize) =>
            setSourceState((value) => ({ ...value, pageSize, page: 1 }))
          }
        />
      )}
    </VStack>
  );
};
