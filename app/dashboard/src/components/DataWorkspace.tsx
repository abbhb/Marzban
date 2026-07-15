import {
  Box,
  Button,
  Card,
  CardBody,
  CardHeader,
  chakra,
  HStack,
  Select,
  Skeleton,
  Stack,
  Text,
  VStack,
} from "@chakra-ui/react";
import { ChevronLeftIcon, ChevronRightIcon } from "@heroicons/react/24/outline";
import { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { LiquidSurface } from "./LiquidSurface";

const PreviousIcon = chakra(ChevronLeftIcon, { baseStyle: { w: 4, h: 4 } });
const NextIcon = chakra(ChevronRightIcon, { baseStyle: { w: 4, h: 4 } });

type DataWorkspaceProps = {
  title: string;
  description?: string;
  total: number;
  toolbar?: ReactNode;
  children: ReactNode;
  isLoading?: boolean;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
};

export const DataWorkspace = ({
  title,
  description,
  total,
  toolbar,
  children,
  isLoading,
  isEmpty,
  emptyTitle,
  emptyDescription,
}: DataWorkspaceProps) => (
  <LiquidSurface
    as={Card}
    tone="strong"
    className="liquid-glass-workspace"
    rounded="3xl"
  >
    <CardHeader px={{ base: 4, md: 6 }} py="5">
      <HStack
        justify="space-between"
        align={{ base: "stretch", lg: "center" }}
        flexDir={{ base: "column", lg: "row" }}
        gap="3"
      >
        <Box>
          <HStack spacing="3">
            <Text fontSize="lg" fontWeight="750">
              {title}
            </Text>
            <Text
              as="span"
              px="2.5"
              py="1"
              rounded="full"
              fontSize="xs"
              fontWeight="700"
              bg="surface.active"
              color="primary.600"
            >
              {total}
            </Text>
          </HStack>
          {description && (
            <Text mt="1" fontSize="sm" color="fg.muted">
              {description}
            </Text>
          )}
        </Box>
        {toolbar && (
          <Box minW="0" w={{ base: "full", lg: "auto" }}>
            {toolbar}
          </Box>
        )}
      </HStack>
    </CardHeader>
    <CardBody p="0">
      {isLoading ? (
        <VStack align="stretch" spacing="0" px={{ base: 4, md: 6 }} pb="5">
          {[0, 1, 2, 3, 4].map((row) => (
            <Skeleton key={row} h="56px" my="1" rounded="xl" />
          ))}
        </VStack>
      ) : isEmpty ? (
        <VStack py="16" px="6" spacing="2" textAlign="center">
          <Text fontWeight="700">{emptyTitle}</Text>
          {emptyDescription && (
            <Text maxW="520px" color="fg.muted" fontSize="sm">
              {emptyDescription}
            </Text>
          )}
        </VStack>
      ) : (
        children
      )}
    </CardBody>
  </LiquidSurface>
);

type PaginationControlsProps = {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
};

export const PaginationControls = ({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: PaginationControlsProps) => {
  const { t } = useTranslation();
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page, 1), pageCount);
  const from = total ? (safePage - 1) * pageSize + 1 : 0;
  const to = Math.min(safePage * pageSize, total);

  return (
    <Stack
      direction={{ base: "column", sm: "row" }}
      justify="space-between"
      align={{ base: "stretch", sm: "center" }}
      px={{ base: 4, md: 6 }}
      py="4"
      borderTopWidth="1px"
      borderColor="border.subtle"
      flexWrap="wrap"
      gap="3"
    >
      <HStack>
        <Select
          size="sm"
          w="72px"
          rounded="xl"
          value={pageSize}
          aria-label={t("itemsPerPage")}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
        >
          {[10, 20, 50, 100].map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </Select>
        <Text fontSize="sm" color="fg.muted">
          {t("itemsPerPage")}
        </Text>
      </HStack>
      <Stack
        direction={{ base: "column", sm: "row" }}
        align={{ base: "stretch", sm: "center" }}
        spacing="3"
      >
        <Text
          fontSize="sm"
          color="fg.muted"
          whiteSpace={{ base: "normal", sm: "nowrap" }}
        >
          {t("commerce.resultRange", { from, to, total })}
        </Text>
        <HStack
          spacing="1"
          justify={{ base: "space-between", sm: "flex-start" }}
        >
          <Button
            size="sm"
            minW="10"
            variant="ghost"
            aria-label={t("previous")}
            isDisabled={safePage <= 1}
            onClick={() => onPageChange(safePage - 1)}
          >
            <PreviousIcon />
          </Button>
          <Text minW="56px" textAlign="center" fontSize="sm" fontWeight="700">
            {safePage} / {pageCount}
          </Text>
          <Button
            size="sm"
            minW="10"
            variant="ghost"
            aria-label={t("next")}
            isDisabled={safePage >= pageCount}
            onClick={() => onPageChange(safePage + 1)}
          >
            <NextIcon />
          </Button>
        </HStack>
      </Stack>
    </Stack>
  );
};
