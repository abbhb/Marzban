import {
  Box,
  chakra,
  HStack,
  IconButton,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
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
    <HStack gap={2} justifyContent="space-between" position="relative">
      <Text as="h1" fontWeight="semibold" fontSize="2xl" flexShrink={0}>
        {t("users")}
      </Text>
      <Box overflowX="auto">
        <HStack alignItems="center">
          {actions}
          <Box position="relative">
            <Menu placement="bottom-end">
              <MenuButton
                as={IconButton}
                variant="outline"
                icon={<MoreActionsIcon />}
                minW="11"
                minH="11"
                aria-label={`${t("header.donation")} / ${t("header.logout")}`}
              />
              <MenuList minW="170px" zIndex={99999} dir={i18n.dir()}>
                <MenuItem
                  as="a"
                  href={DONATION_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  maxW="170px"
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
                  to="/login"
                  maxW="170px"
                  fontSize="sm"
                  icon={<LogoutIcon />}
                >
                  {t("header.logout")}
                </MenuItem>
              </MenuList>
            </Menu>
            {showDonationNotif && (
              <NotificationCircle top="1" right="1" pointerEvents="none" />
            )}
          </Box>

          <Box display={{ base: "none", md: "block" }}>
            <Language />
          </Box>

          <IconButton
            variant="outline"
            aria-label={t("portal.switchTheme")}
            minW="11"
            minH="11"
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
            pr="2"
            __css={{
              "&  span": {
                display: "inline-flex",
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
      </Box>
    </HStack>
  );
};
