import {
  Box,
  Button,
  chakra,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerOverlay,
  Flex,
  HStack,
  IconButton,
  Text,
  useColorMode,
  useDisclosure,
  useToast,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowLeftOnRectangleIcon,
  Bars3Icon,
  HomeIcon,
  LinkIcon,
  MoonIcon,
  ShoppingBagIcon,
  SunIcon,
  WalletIcon,
} from "@heroicons/react/24/outline";
import { Footer } from "components/Footer";
import { Language } from "components/Language";
import { LiquidSurface } from "components/LiquidSurface";
import { LogoIcon } from "pages/Login";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  NavLink,
  Outlet,
  useLoaderData,
  useLocation,
  useNavigate,
  useOutletContext,
} from "react-router-dom";
import { portalFetch } from "service/http";
import {
  PortalAccount,
  PortalPurchaseResult,
  SubscriptionPlan,
  WalletTransaction,
} from "types/Commerce";
import { removePortalAuthToken } from "utils/portalAuthStorage";
import { updateThemeColor } from "utils/themeColor";

const iconStyle = { baseStyle: { w: 5, h: 5 } };
const OverviewIcon = chakra(HomeIcon, iconStyle);
const PlansIcon = chakra(ShoppingBagIcon, iconStyle);
const AccessIcon = chakra(LinkIcon, iconStyle);
const WalletNavIcon = chakra(WalletIcon, iconStyle);
const LogoutIcon = chakra(ArrowLeftOnRectangleIcon, iconStyle);
const MenuIcon = chakra(Bars3Icon, iconStyle);
const DarkIcon = chakra(MoonIcon, iconStyle);
const LightIcon = chakra(SunIcon, iconStyle);

type PortalContext = {
  me: PortalAccount;
  plans: SubscriptionPlan[];
  transactions: WalletTransaction[];
  plansError: boolean;
  transactionsError: boolean;
  supplementalLoading: boolean;
  applyPurchase: (result: PortalPurchaseResult) => void;
  refresh: () => Promise<void>;
};

export const usePortalContext = () => useOutletContext<PortalContext>();

const navigation = [
  { to: "/portal", key: "portal.navOverview", icon: OverviewIcon, end: true },
  { to: "/portal/plans", key: "portal.navPlans", icon: PlansIcon },
  { to: "/portal/access", key: "portal.navAccess", icon: AccessIcon },
  { to: "/portal/wallet", key: "portal.navWallet", icon: WalletNavIcon },
];

const pageTitles: Record<string, string> = {
  "/portal": "portal.overviewTitle",
  "/portal/": "portal.overviewTitle",
  "/portal/plans": "portal.storeTitle",
  "/portal/access": "portal.accessTitle",
  "/portal/wallet": "portal.walletTitle",
};

const PortalNavigation = ({ onNavigate }: { onNavigate?: () => void }) => {
  const { t } = useTranslation();
  return (
    <VStack
      as="nav"
      spacing="2"
      align="stretch"
      aria-label={t("portal.primaryNavigation")}
      className="liquid-sidebar-navigation"
    >
      {navigation.map(({ to, key, icon: Icon, end }) => (
        <Button
          key={to}
          as={NavLink}
          to={to}
          end={end}
          justifyContent="flex-start"
          minH="11"
          px="4"
          leftIcon={<Icon />}
          variant="ghost"
          className="liquid-nav-item"
          color="fg.muted"
          _hover={{ color: "fg.default" }}
          _activeLink={{
            color: "primary.600",
          }}
          onClick={onNavigate}
        >
          {t(key)}
        </Button>
      ))}
    </VStack>
  );
};

export const PortalLayout = () => {
  const initialAccount = useLoaderData() as PortalAccount;
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const mobileNav = useDisclosure();
  const { colorMode, toggleColorMode } = useColorMode();
  const [me, setMe] = useState(initialAccount);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [transactions, setTransactions] = useState<WalletTransaction[]>([]);
  const [plansError, setPlansError] = useState(false);
  const [transactionsError, setTransactionsError] = useState(false);
  const [supplementalLoading, setSupplementalLoading] = useState(true);

  const loadSupplemental = useCallback(async () => {
    setSupplementalLoading(true);
    setPlansError(false);
    setTransactionsError(false);
    const [visiblePlans, ledger] = await Promise.allSettled([
      portalFetch<SubscriptionPlan[]>("/portal/plans"),
      portalFetch<WalletTransaction[]>("/portal/wallet/transactions"),
    ]);
    if (visiblePlans.status === "fulfilled") setPlans(visiblePlans.value);
    if (ledger.status === "fulfilled") setTransactions(ledger.value);
    setPlansError(visiblePlans.status === "rejected");
    setTransactionsError(ledger.status === "rejected");
    if (visiblePlans.status === "rejected" || ledger.status === "rejected") {
      toast({
        title: t("portal.requestFailed"),
        status: "error",
        position: "top",
      });
    }
    setSupplementalLoading(false);
  }, [t, toast]);

  const refresh = useCallback(async () => {
    setSupplementalLoading(true);
    setPlansError(false);
    setTransactionsError(false);
    const [profile, visiblePlans, ledger] = await Promise.allSettled([
      portalFetch<PortalAccount>("/portal/me"),
      portalFetch<SubscriptionPlan[]>("/portal/plans"),
      portalFetch<WalletTransaction[]>("/portal/wallet/transactions"),
    ]);
    if (profile.status === "fulfilled") setMe(profile.value);
    if (visiblePlans.status === "fulfilled") setPlans(visiblePlans.value);
    if (ledger.status === "fulfilled") setTransactions(ledger.value);
    setPlansError(visiblePlans.status === "rejected");
    setTransactionsError(ledger.status === "rejected");
    if (
      profile.status === "rejected" ||
      visiblePlans.status === "rejected" ||
      ledger.status === "rejected"
    ) {
      toast({
        title: t("portal.requestFailed"),
        status: "error",
        position: "top",
      });
    }
    setSupplementalLoading(false);
  }, [t, toast]);

  useEffect(() => {
    loadSupplemental();
  }, [loadSupplemental]);

  const logout = () => {
    removePortalAuthToken();
    navigate("/portal/login");
  };

  const switchTheme = () => {
    updateThemeColor(colorMode === "dark" ? "light" : "dark");
    toggleColorMode();
  };

  const applyPurchase = useCallback((result: PortalPurchaseResult) => {
    setMe((account) => ({
      ...account,
      wallet_balance_minor: result.wallet_balance_minor,
      subscription: result.subscription,
      usage: result.usage,
    }));
  }, []);

  const title = t(pageTitles[location.pathname] || "portal.dashboardTitle");
  const context = useMemo(
    () => ({
      me,
      plans,
      transactions,
      plansError,
      transactionsError,
      supplementalLoading,
      applyPurchase,
      refresh,
    }),
    [
      me,
      plans,
      transactions,
      plansError,
      transactionsError,
      supplementalLoading,
      applyPurchase,
      refresh,
    ]
  );

  const sidebar = (
    <VStack
      h="full"
      align="stretch"
      spacing="6"
      className="liquid-sidebar-stack"
    >
      <HStack px="3" spacing="3">
        <Box transform="scale(.72)" transformOrigin="left center" w="10" h="10">
          <LogoIcon />
        </Box>
        <Box>
          <Text fontWeight="700" letterSpacing="-.02em">
            {t("portal.portalName")}
          </Text>
          <Text fontSize="xs" color="fg.subtle">
            {t("portal.portalTagline")}
          </Text>
        </Box>
      </HStack>
      <PortalNavigation onNavigate={mobileNav.onClose} />
      <Box flex="1" />
      <Box layerStyle="glassSubtle" rounded="2xl" p="3">
        <Text fontSize="sm" fontWeight="600" noOfLines={1}>
          {me.username}
        </Text>
        <Text fontSize="xs" color="fg.subtle" noOfLines={1}>
          {me.subscription?.plan_name || t("portal.noPlan")}
        </Text>
      </Box>
      <Button
        variant="ghost"
        className="liquid-sidebar-logout"
        justifyContent="flex-start"
        minH="11"
        leftIcon={<LogoutIcon />}
        color="fg.muted"
        onClick={logout}
      >
        {t("header.logout")}
      </Button>
    </VStack>
  );

  return (
    <Flex minH="100vh" className="portal-canvas">
      <Box
        as="aside"
        display={{ base: "none", lg: "block" }}
        position="fixed"
        insetInlineStart="0"
        top="0"
        w="260px"
        h="100vh"
        p="4"
        zIndex="20"
      >
        <LiquidSurface
          tone="glass"
          bg="surface.sidebar"
          className="glass-surface liquid-shell-surface liquid-sidebar-surface"
          rounded="3xl"
          h="full"
          p="4"
        >
          {sidebar}
        </LiquidSurface>
      </Box>

      <Drawer
        isOpen={mobileNav.isOpen}
        placement={i18n.dir() === "rtl" ? "right" : "left"}
        onClose={mobileNav.onClose}
      >
        <DrawerOverlay backdropFilter="var(--marzban-overlay-filter)" />
        <DrawerContent
          aria-label={t("portal.primaryNavigation")}
          bg="transparent"
          boxShadow="none"
          p="3"
        >
          <LiquidSurface
            tone="glass"
            bg="surface.sidebar"
            className="glass-surface liquid-shell-surface liquid-sidebar-surface"
            rounded="3xl"
            h="full"
            p="4"
          >
            <DrawerCloseButton
              aria-label={t("close")}
              top="5"
              insetInlineEnd="5"
              minW="11"
              minH="11"
            />
            <DrawerBody p="0" pt="2">
              {sidebar}
            </DrawerBody>
          </LiquidSurface>
        </DrawerContent>
      </Drawer>

      <Box flex="1" minW="0" ms={{ base: 0, lg: "260px" }}>
        <LiquidSurface
          as="header"
          tone="glass"
          className="glass-surface liquid-topbar"
          position="sticky"
          top="0"
          zIndex="10"
          minH="72px"
          px={{ base: 4, md: 7 }}
          overflow="visible"
        >
          <HStack minH="72px" justify="space-between">
            <HStack spacing="3">
              <IconButton
                display={{ base: "inline-flex", lg: "none" }}
                aria-label={t("portal.openNavigation")}
                icon={<MenuIcon />}
                minW="11"
                minH="11"
                variant="ghost"
                onClick={mobileNav.onOpen}
              />
              <Box>
                <Text
                  as="h1"
                  fontWeight="700"
                  fontSize={{ base: "lg", md: "xl" }}
                  letterSpacing="-.025em"
                >
                  {title}
                </Text>
                <Text
                  display={{ base: "none", md: "block" }}
                  fontSize="xs"
                  color="fg.subtle"
                >
                  {t("portal.signedInAs", { username: me.username })}
                </Text>
              </Box>
            </HStack>
            <HStack>
              <Language />
              <IconButton
                aria-label={t("portal.switchTheme")}
                icon={colorMode === "light" ? <DarkIcon /> : <LightIcon />}
                minW="11"
                minH="11"
                variant="ghost"
                onClick={switchTheme}
              />
            </HStack>
          </HStack>
        </LiquidSurface>

        <Box as="main" px={{ base: 4, md: 7 }} pt={{ base: 5, md: 7 }} pb="8">
          <Box maxW="1440px" mx="auto" className="liquid-page-enter">
            <Outlet context={context} />
            <Footer mt="10" />
          </Box>
        </Box>
      </Box>
    </Flex>
  );
};
