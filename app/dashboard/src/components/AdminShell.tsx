import {
  Box,
  Button,
  Divider,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerOverlay,
  Flex,
  HStack,
  Icon,
  IconButton,
  Text,
  useColorMode,
  useDisclosure,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowLeftOnRectangleIcon,
  BanknotesIcon,
  Bars3Icon,
  ChartPieIcon,
  Cog6ToothIcon,
  DocumentMinusIcon,
  LinkIcon,
  MoonIcon,
  ShieldCheckIcon,
  SquaresPlusIcon,
  SunIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import { Language } from "components/Language";
import { ElementType, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLoaderData, useLocation, useNavigate } from "react-router-dom";
import { UserApi } from "types/User";
import { removeAuthToken } from "utils/authStorage";
import { updateThemeColor } from "utils/themeColor";

type AdminShellProps = {
  children: ReactNode;
};

type NavigationItem = {
  icon: ElementType;
  label: string;
  path: string;
  panel?: string;
};

type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

type NavigationProps = {
  groups: NavigationGroup[];
  maintenanceItems: NavigationItem[];
  maintenanceLabel: string;
  label: string;
  onNavigate?: () => void;
};

const Navigation = ({
  groups,
  maintenanceItems,
  maintenanceLabel,
  label,
  onNavigate,
}: NavigationProps) => {
  const navigate = useNavigate();
  const location = useLocation();
  const activePanel = new URLSearchParams(location.search).get("panel");

  const go = (item: NavigationItem) => {
    navigate(item.panel ? `/?panel=${item.panel}` : item.path);
    onNavigate?.();
  };

  const renderItem = (item: NavigationItem, danger = false) => {
    const isActive = item.panel
      ? location.pathname === "/" && activePanel === item.panel
      : location.pathname === item.path && !activePanel;

    return (
      <Button
        key={`${item.path}:${item.panel || "page"}`}
        aria-current={isActive ? "page" : undefined}
        justifyContent="flex-start"
        leftIcon={<Icon as={item.icon} boxSize="5" />}
        onClick={() => go(item)}
        minH="11"
        px="3"
        rounded="xl"
        variant="ghost"
        bg={isActive ? (danger ? "red.50" : "surface.active") : "transparent"}
        color={danger ? "red.600" : isActive ? "primary.600" : "fg.muted"}
        fontWeight={isActive ? "semibold" : "medium"}
        _dark={{
          bg: isActive ? (danger ? "rgba(245, 101, 101, 0.14)" : "surface.active") : "transparent",
          color: danger ? "red.300" : isActive ? "primary.300" : "fg.muted",
        }}
        _hover={{
          bg: danger ? "rgba(245, 101, 101, 0.12)" : "surface.hover",
          color: danger ? undefined : "fg.default",
        }}
      >
        {item.label}
      </Button>
    );
  };

  return (
    <VStack
      as="nav"
      aria-label={label}
      align="stretch"
      spacing="5"
      w="full"
      flex="1"
      minH="0"
      overflowY="auto"
      pe="1"
    >
      {groups.map((group) => (
        <VStack
          key={group.label}
          role="group"
          aria-label={group.label}
          align="stretch"
          spacing="1"
        >
          <Text
            px="3"
            mb="1"
            color="fg.subtle"
            fontSize="xs"
            fontWeight="700"
            letterSpacing=".08em"
            textTransform="uppercase"
          >
            {group.label}
          </Text>
          {group.items.map((item) => renderItem(item))}
        </VStack>
      ))}
      <Box flex="1" minH="2" />
      {!!maintenanceItems.length && (
        <VStack role="group" aria-label={maintenanceLabel} align="stretch" spacing="2">
          <Divider borderColor="border.subtle" />
          {maintenanceItems.map((item) => renderItem(item, true))}
        </VStack>
      )}
    </VStack>
  );
};

export const AdminShell = ({ children }: AdminShellProps) => {
  const { t, i18n } = useTranslation();
  const drawer = useDisclosure();
  const navigate = useNavigate();
  const { colorMode, toggleColorMode } = useColorMode();
  const userData = useLoaderData() as UserApi;
  const isSudo = Boolean(userData?.is_sudo);
  const navigationLabel = t("admin.primaryNavigation");
  const groups: NavigationGroup[] = [
    {
      label: t("admin.accountManagement"),
      items: [
        { icon: UsersIcon, label: t("users"), path: "/" },
        ...(isSudo
          ? [{ icon: BanknotesIcon, label: t("header.commerce"), path: "/commerce" }]
          : []),
      ],
    },
    ...(isSudo
      ? [
          {
            label: t("admin.infrastructure"),
            items: [
              { icon: LinkIcon, label: t("header.hostSettings"), path: "/", panel: "hosts" },
              { icon: SquaresPlusIcon, label: t("header.nodeSettings"), path: "/", panel: "nodes" },
              { icon: ChartPieIcon, label: t("header.nodesUsage"), path: "/", panel: "node-usage" },
            ],
          },
          {
            label: t("admin.systemSettings"),
            items: [
              {
                icon: ShieldCheckIcon,
                label: t("header.subscriptionSecurity"),
                path: "/",
                panel: "subscription-security",
              },
              { icon: Cog6ToothIcon, label: t("core.title"), path: "/", panel: "core" },
            ],
          },
        ]
      : []),
  ];
  const maintenanceItems: NavigationItem[] = isSudo
    ? [
        {
          icon: DocumentMinusIcon,
          label: t("resetAllUsage"),
          path: "/",
          panel: "reset-usage",
        },
      ]
    : [];

  const switchTheme = () => {
    updateThemeColor(colorMode === "dark" ? "light" : "dark");
    toggleColorMode();
  };

  const logout = () => {
    removeAuthToken();
    drawer.onClose();
    navigate("/login");
  };

  const sidebar = (
    <VStack align="stretch" h="full" spacing="6">
      <HStack px="2" spacing="3">
        <Flex
          align="center"
          justify="center"
          boxSize="10"
          rounded="2xl"
          color="white"
          bgGradient="linear(to-br, primary.400, purple.500)"
          boxShadow="0 12px 30px rgba(57, 111, 228, 0.28)"
        >
          <Icon as={ShieldCheckIcon} boxSize="5" />
        </Flex>
        <Box>
          <Text fontSize="lg" fontWeight="bold" lineHeight="short">
            Marzban
          </Text>
          <Text color="gray.500" fontSize="xs">
            {t("admin.console")}
          </Text>
        </Box>
      </HStack>
      <Navigation
        groups={groups}
        maintenanceItems={maintenanceItems}
        maintenanceLabel={t("admin.maintenance")}
        label={navigationLabel}
        onNavigate={drawer.onClose}
      />
      <HStack pt="3" borderTop="1px solid" borderColor="border.subtle" justify="space-between">
        <Language />
        <IconButton
          aria-label={t("portal.switchTheme")}
          icon={<Icon as={colorMode === "light" ? MoonIcon : SunIcon} boxSize="5" />}
          minW="11"
          minH="11"
          variant="ghost"
          onClick={switchTheme}
        />
        <IconButton
          aria-label={t("header.logout")}
          icon={<Icon as={ArrowLeftOnRectangleIcon} boxSize="5" />}
          minW="11"
          minH="11"
          variant="ghost"
          onClick={logout}
        />
      </HStack>
    </VStack>
  );

  return (
    <Flex minH="100vh" w="full" bg="transparent" align="stretch">
      <Box
        as="aside"
        display={{ base: "none", lg: "block" }}
        position="sticky"
        top="0"
        h="100vh"
        w="260px"
        flexShrink="0"
        p="4"
      >
        <Box layerStyle="glass" h="full" p="4" boxShadow="glass.lg">
          {sidebar}
        </Box>
      </Box>

      <Box flex="1" minW="0">
        <HStack
          display={{ base: "flex", lg: "none" }}
          position="sticky"
          top="0"
          zIndex="sticky"
          justify="space-between"
          px="4"
          py="3"
          layerStyle="glassTopbar"
        >
          <HStack>
            <IconButton
              aria-label={t("portal.openNavigation")}
              icon={<Icon as={Bars3Icon} boxSize="5" />}
              onClick={drawer.onOpen}
              minW="11"
              minH="11"
              variant="ghost"
            />
            <Text fontWeight="bold">Marzban</Text>
          </HStack>
        </HStack>
        <Box as="main">{children}</Box>
      </Box>

      <Drawer
        isOpen={drawer.isOpen}
        placement={i18n.dir() === "rtl" ? "right" : "left"}
        onClose={drawer.onClose}
      >
        <DrawerOverlay backdropFilter="var(--marzban-glass-filter-subtle)" />
        <DrawerContent aria-label={navigationLabel} bg="transparent" boxShadow="none" p="3">
          <Box layerStyle="glass" h="full" p="4" boxShadow="glass.lg">
            <DrawerCloseButton aria-label={t("close")} minW="11" minH="11" top="5" insetInlineEnd="5" />
            <DrawerBody p="0" pt="2">
              {sidebar}
            </DrawerBody>
          </Box>
        </DrawerContent>
      </Drawer>
    </Flex>
  );
};
