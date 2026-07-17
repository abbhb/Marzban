import {
  Box,
  chakra,
  HStack,
  IconButton,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
  Text,
  useColorMode,
} from "@chakra-ui/react";
import {
  ArrowLeftOnRectangleIcon,
  CurrencyDollarIcon,
  EllipsisHorizontalIcon,
  MoonIcon,
  SunIcon,
} from "@heroicons/react/24/outline";
import { DONATION_URL, REPO_URL } from "constants/Project";
import differenceInDays from "date-fns/differenceInDays";
import isValid from "date-fns/isValid";
import { FC, ReactNode, useState } from "react";
import GitHubButton from "react-github-btn";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { updateThemeColor } from "utils/themeColor";
import { Language } from "./Language";

type HeaderProps = {
  actions?: ReactNode;
};
const iconProps = {
  baseStyle: {
    w: 4,
    h: 4,
  },
};

const DarkIcon = chakra(MoonIcon, iconProps);
const LightIcon = chakra(SunIcon, iconProps);
const MoreActionsIcon = chakra(EllipsisHorizontalIcon, iconProps);
const LogoutIcon = chakra(ArrowLeftOnRectangleIcon, iconProps);
const DonationIcon = chakra(CurrencyDollarIcon, iconProps);
const NotificationCircle = chakra(Box, {
  baseStyle: {
    bg: "yellow.500",
    w: "2",
    h: "2",
    rounded: "full",
    position: "absolute",
  },
});

const NOTIFICATION_KEY = "marzban-menu-notification";

export const shouldShowDonation = (): boolean => {
  const date = localStorage.getItem(NOTIFICATION_KEY);
  if (!date) return true;
  try {
    if (date && isValid(parseInt(date))) {
      if (differenceInDays(new Date(), new Date(parseInt(date))) >= 7)
        return true;
      return false;
    }
    return true;
  } catch (err) {
    return true;
  }
};

export const Header: FC<HeaderProps> = ({ actions }) => {
  const { t, i18n } = useTranslation();
  const { colorMode, toggleColorMode } = useColorMode();
  const [showDonationNotif, setShowDonationNotif] = useState(
    shouldShowDonation()
  );
  const gBtnColor = colorMode === "dark" ? "dark_dimmed" : colorMode;

  const handleOnClose = () => {
    localStorage.setItem(NOTIFICATION_KEY, new Date().getTime().toString());
    setShowDonationNotif(false);
  };

  return (
    <HStack
      gap={4}
      justifyContent="space-between"
      position="relative"
      minW="0"
    >
      <Text as="h1" fontWeight="semibold" fontSize="2xl" flexShrink={0}>
        {t("users")}
      </Text>
      <HStack
        alignItems="center"
        flexShrink={0}
        gap="1"
        p="1"
        rounded="xl"
        bg="surface.inset"
        boxShadow="glass-subtle"
        _dark={{ boxShadow: "glass-subtle-dark" }}
      >
        <Box minW="0" maxW={{ base: "28vw", lg: "none" }} overflowX="auto">
          {actions}
        </Box>
        <Box position="relative">
          <Menu placement="bottom-end">
            <MenuButton
              as={IconButton}
              size="sm"
              variant="ghost"
              icon={<MoreActionsIcon />}
              w="9"
              h="9"
              minW="9"
              aria-label={`${t("header.donation")} / ${t("header.logout")}`}
            />
            <Portal>
              <MenuList minW="184px" zIndex="popover" dir={i18n.dir()}>
                <MenuItem
                  as="a"
                  href={DONATION_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  minH="9"
                  fontSize="sm"
                  icon={<DonationIcon />}
                  position="relative"
                  onClick={handleOnClose}
                >
                  {t("header.donation")}{" "}
                  {showDonationNotif && (
                    <NotificationCircle top="3" right="2" />
                  )}
                </MenuItem>
                <MenuItem
                  as={Link}
                  to="/login/admin"
                  minH="9"
                  fontSize="sm"
                  icon={<LogoutIcon />}
                >
                  {t("header.logout")}
                </MenuItem>
              </MenuList>
            </Portal>
          </Menu>
          {showDonationNotif && (
            <NotificationCircle top="1" right="1" pointerEvents="none" />
          )}
        </Box>

        <Box display={{ base: "none", md: "block" }}>
          <Language />
        </Box>

        <IconButton
          size="sm"
          variant="ghost"
          aria-label={t("portal.switchTheme")}
          w="9"
          h="9"
          minW="9"
          onClick={() => {
            updateThemeColor(colorMode == "dark" ? "light" : "dark");
            toggleColorMode();
          }}
        >
          {colorMode === "light" ? <DarkIcon /> : <LightIcon />}
        </IconButton>

        <Box
          css={{ direction: "ltr" }}
          display={{ base: "none", xl: "flex" }}
          alignItems="center"
          h="7"
          px="1"
          overflow="hidden"
          lineHeight="0"
          __css={{
            "& span": {
              display: "inline-flex",
            },
            "& iframe": {
              display: "block",
            },
          }}
        >
          <GitHubButton
            href={REPO_URL}
            data-color-scheme={`no-preference: ${gBtnColor}; light: ${gBtnColor}; dark: ${gBtnColor};`}
            data-size="large"
            data-show-count="true"
            aria-label="Star Marzban on GitHub"
          >
            Star
          </GitHubButton>
        </Box>
      </HStack>
    </HStack>
  );
};
