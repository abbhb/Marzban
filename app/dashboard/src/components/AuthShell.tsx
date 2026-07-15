import {
  Box,
  chakra,
  Flex,
  Grid,
  Heading,
  HStack,
  Icon,
  IconButton,
  Text,
  useColorMode,
  usePrefersReducedMotion,
  VStack,
} from "@chakra-ui/react";
import { keyframes } from "@emotion/react";
import { MoonIcon, SunIcon } from "@heroicons/react/24/outline";
import { ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import { ReactComponent as Logo } from "assets/logo.svg";
import { Footer } from "components/Footer";
import { Language } from "components/Language";
import { LiquidSurface } from "components/LiquidSurface";
import { updateThemeColor } from "utils/themeColor";

const breathe = keyframes`
  0%, 100% { opacity: .52; transform: scale(.96); }
  50% { opacity: .84; transform: scale(1.04); }
`;

export const LogoIcon = chakra(Logo, {
  baseStyle: {
    strokeWidth: "10px",
    w: 12,
    h: 12,
  },
});

type AuthShellProps = {
  children: ReactNode;
  title: ReactNode;
  subtitle: ReactNode;
  footer?: ReactNode;
  context?: "admin" | "portal";
};

export const AuthShell = ({
  children,
  title,
  subtitle,
  footer,
  context = "portal",
}: AuthShellProps) => {
  const { colorMode, toggleColorMode } = useColorMode();
  const reduceMotion = usePrefersReducedMotion();
  const { t } = useTranslation();
  const titleId = useId();
  const subtitleId = useId();
  const isAdmin = context === "admin";

  const switchTheme = () => {
    updateThemeColor(colorMode === "dark" ? "light" : "dark");
    toggleColorMode();
  };

  return (
    <Flex
      as="main"
      minH="100dvh"
      w="full"
      position="relative"
      overflowX="hidden"
      direction="column"
      px={{ base: "4", sm: "6", lg: "10" }}
      py={{ base: "4", md: "6" }}
    >
      <HStack
        position="relative"
        zIndex="2"
        justify="flex-end"
        maxW="1120px"
        w="full"
        mx="auto"
        spacing="2"
      >
        <Language />
        <IconButton
          aria-label={t("portal.switchTheme")}
          icon={
            <Icon as={colorMode === "light" ? MoonIcon : SunIcon} boxSize="5" />
          }
          minW="11"
          minH="11"
          variant="outline"
          onClick={switchTheme}
        />
      </HStack>

      <Flex
        position="relative"
        zIndex="1"
        flex="1"
        w="full"
        align="center"
        justify="center"
        py={{ base: "6", md: "8" }}
      >
        <LiquidSurface
          as="section"
          tone="strong"
          aria-labelledby={titleId}
          aria-describedby={subtitleId}
          w="full"
          maxW="1040px"
          rounded={{ base: "3xl", md: "32px" }}
        >
          <Grid
            templateColumns={{
              base: "1fr",
              lg: "minmax(310px, .78fr) minmax(0, 1.22fr)",
            }}
          >
            <VStack
              display={{ base: "none", lg: "flex" }}
              position="relative"
              isolation="isolate"
              align="stretch"
              justify="space-between"
              minH="600px"
              p={{ lg: "10", xl: "12" }}
              overflow="hidden"
              borderInlineEnd="1px solid"
              borderColor="border.glass"
              bgGradient={
                isAdmin
                  ? "linear(145deg, rgba(73, 115, 255, .18), rgba(139, 92, 246, .08) 58%, rgba(255, 255, 255, .03))"
                  : "linear(145deg, rgba(38, 112, 232, .16), rgba(45, 212, 191, .09) 58%, rgba(255, 255, 255, .03))"
              }
            >
              <HStack spacing="3" position="relative" zIndex="1">
                <Flex
                  boxSize="12"
                  align="center"
                  justify="center"
                  rounded="2xl"
                  bg="rgba(255, 255, 255, .34)"
                  color="primary.600"
                  boxShadow="inset 0 1px 0 rgba(255,255,255,.72), 0 12px 30px rgba(31,60,105,.14)"
                  _dark={{
                    bg: "rgba(255, 255, 255, .08)",
                    color: "primary.300",
                  }}
                >
                  <LogoIcon w="7" h="7" />
                </Flex>
                <Box>
                  <Text fontSize="xl" fontWeight="800" letterSpacing="-.035em">
                    Marzban
                  </Text>
                  <Text
                    fontSize="xs"
                    color="fg.subtle"
                    fontWeight="600"
                    letterSpacing=".06em"
                  >
                    {isAdmin ? t("admin.console") : t("portal.portalTagline")}
                  </Text>
                </Box>
              </HStack>

              <Flex
                aria-hidden="true"
                position="relative"
                zIndex="1"
                h="280px"
                align="center"
                justify="center"
              >
                {[208, 156, 112].map((size, index) => (
                  <Box
                    key={size}
                    position="absolute"
                    boxSize={`${size}px`}
                    rounded="full"
                    border="1px solid"
                    borderColor="border.glass"
                    opacity={0.3 + index * 0.16}
                    animation={
                      reduceMotion
                        ? undefined
                        : `${breathe} ${8 + index * 1.4}s ease-in-out ${
                            index * -1.3
                          }s infinite`
                    }
                  />
                ))}
                <Flex
                  boxSize="24"
                  align="center"
                  justify="center"
                  rounded="full"
                  color={isAdmin ? "purple.600" : "primary.600"}
                  bg="rgba(255, 255, 255, .30)"
                  boxShadow="inset 0 1px 0 rgba(255,255,255,.72), 0 22px 54px rgba(31,60,105,.17)"
                  _dark={{
                    bg: "rgba(255, 255, 255, .08)",
                    color: isAdmin ? "purple.300" : "primary.300",
                  }}
                >
                  <LogoIcon w="12" h="12" />
                </Flex>
                <Box
                  position="absolute"
                  top="42px"
                  right="54px"
                  boxSize="3"
                  rounded="full"
                  bg={isAdmin ? "purple.300" : "cyan.300"}
                  boxShadow={
                    isAdmin
                      ? "0 0 24px rgba(183, 148, 244, .72)"
                      : "0 0 24px rgba(103, 232, 249, .72)"
                  }
                />
                <Box
                  position="absolute"
                  bottom="52px"
                  left="62px"
                  boxSize="2"
                  rounded="full"
                  bg="primary.300"
                  boxShadow="0 0 20px rgba(147, 197, 253, .72)"
                />
              </Flex>

              <Box h="14" position="relative" aria-hidden="true">
                {[0, 1, 2].map((index) => (
                  <Box
                    key={index}
                    position="absolute"
                    insetInlineStart={`${index * 42}px`}
                    bottom="0"
                    boxSize={`${38 + index * 10}px`}
                    rounded="full"
                    border="1px solid"
                    borderColor="border.glass"
                    opacity={0.72 - index * 0.14}
                    animation={
                      reduceMotion
                        ? undefined
                        : `${breathe} ${6 + index * 1.2}s ease-in-out ${
                            index * -1.1
                          }s infinite`
                    }
                  />
                ))}
              </Box>
            </VStack>

            <Flex
              align="center"
              justify="center"
              minH={{ base: "auto", lg: "600px" }}
              px={{ base: "5", sm: "9", md: "14", xl: "16" }}
              py={{ base: "8", sm: "10", lg: "12" }}
            >
              <VStack align="stretch" spacing="6" w="full" maxW="420px">
                <HStack display={{ base: "flex", lg: "none" }} spacing="3">
                  <Flex
                    boxSize="11"
                    align="center"
                    justify="center"
                    rounded="2xl"
                    bg="surface.active"
                    color="primary.600"
                    _dark={{ color: "primary.300" }}
                  >
                    <LogoIcon w="6" h="6" />
                  </Flex>
                  <Box>
                    <Text fontWeight="800" letterSpacing="-.025em">
                      Marzban
                    </Text>
                    <Text fontSize="xs" color="fg.subtle">
                      {isAdmin ? t("admin.console") : t("portal.portalTagline")}
                    </Text>
                  </Box>
                </HStack>

                <Box>
                  <Heading
                    id={titleId}
                    as="h1"
                    size="lg"
                    letterSpacing="-.035em"
                  >
                    {title}
                  </Heading>
                  <Text
                    id={subtitleId}
                    mt="2"
                    color="fg.muted"
                    lineHeight="tall"
                  >
                    {subtitle}
                  </Text>
                </Box>

                {children}

                {footer && (
                  <VStack
                    align="stretch"
                    spacing="3"
                    pt="1"
                    color="fg.muted"
                    fontSize="sm"
                  >
                    {footer}
                  </VStack>
                )}
              </VStack>
            </Flex>
          </Grid>
        </LiquidSurface>
      </Flex>

      <Footer position="relative" zIndex="1" />
    </Flex>
  );
};
