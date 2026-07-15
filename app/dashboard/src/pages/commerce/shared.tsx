import {
  chakra,
  Input,
  InputGroup,
  InputLeftElement,
  InputRightElement,
  IconButton,
  Spinner,
} from "@chakra-ui/react";
import { MagnifyingGlassIcon, XMarkIcon } from "@heroicons/react/24/outline";
import { Dispatch, SetStateAction, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const SearchIcon = chakra(MagnifyingGlassIcon, { baseStyle: { w: 4, h: 4 } });
const ClearIcon = chakra(XMarkIcon, { baseStyle: { w: 4, h: 4 } });

export type PageState = {
  page: number;
  pageSize: number;
  search: string;
  status: string;
};

export const initialPageState: PageState = { page: 1, pageSize: 20, search: "", status: "" };

export const useDebouncedValue = <T,>(value: T, delay = 300): T => {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
};

export const pageUrl = (path: string, state: PageState, extra: Record<string, string> = {}) => {
  const params = new URLSearchParams({
    page: String(state.page),
    page_size: String(state.pageSize),
  });
  if (state.search.trim()) params.set("search", state.search.trim());
  if (state.status) params.set("status", state.status);
  Object.entries(extra).forEach(([key, value]) => value && params.set(key, value));
  return `${path}?${params.toString()}`;
};

type WorkspaceSearchProps = {
  state: PageState;
  setState: Dispatch<SetStateAction<PageState>>;
  isLoading?: boolean;
  placeholder?: string;
};

export const WorkspaceSearch = ({ state, setState, isLoading, placeholder }: WorkspaceSearchProps) => {
  const { t } = useTranslation();
  return (
    <InputGroup size="sm" w={{ base: "full", md: "280px" }}>
      <InputLeftElement pointerEvents="none"><SearchIcon color="fg.subtle" /></InputLeftElement>
      <Input
        value={state.search}
        placeholder={placeholder || t("search")}
        rounded="xl"
        bg="surface.input"
        onChange={(event) => setState((value) => ({ ...value, search: event.target.value, page: 1 }))}
      />
      <InputRightElement>
        {isLoading ? <Spinner size="xs" /> : state.search ? (
          <IconButton
            size="xs"
            variant="ghost"
            aria-label={t("commerce.clear")}
            icon={<ClearIcon />}
            onClick={() => setState((value) => ({ ...value, search: "", page: 1 }))}
          />
        ) : null}
      </InputRightElement>
    </InputGroup>
  );
};

export const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;
