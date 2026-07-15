import {
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  Grid,
  Heading,
  HStack,
  Progress,
  SimpleGrid,
  Stat,
  StatLabel,
  StatNumber,
  Text,
  VStack,
} from "@chakra-ui/react";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { formatBytes } from "utils/formatByte";
import { usePortalContext } from "./PortalLayout";

const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;

export const PortalOverview = () => {
  const { me } = usePortalContext();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const limit = me.usage.data_limit || me.subscription?.data_limit || 0;
  const percent = limit
    ? Math.min(100, (me.usage.used_traffic / limit) * 100)
    : 0;
  const active = me.usage.status === "active";
  const canIssueMgma = Boolean(
    me.user_id && ["active", "on_hold"].includes(me.usage.status || "")
  );

  return (
    <VStack align="stretch" spacing="6">
      <Grid
        templateColumns={{
          base: "1fr",
          xl: "minmax(0, 1.55fr) minmax(320px, .75fr)",
        }}
        gap="5"
      >
        <Box
          layerStyle="glassHero"
          className="glass-surface"
          rounded="3xl"
          p={{ base: 6, md: 8 }}
          minH={{ md: "260px" }}
          position="relative"
          overflow="hidden"
        >
          <Badge
            colorScheme={active ? "green" : "orange"}
            rounded="full"
            px="3"
            py="1"
          >
            {me.usage.status
              ? t(`status.${me.usage.status}`)
              : t("portal.notActivated")}
          </Badge>
          <Heading
            mt="5"
            size={{ base: "lg", md: "xl" }}
            maxW="700px"
            letterSpacing="-.04em"
          >
            {t("portal.welcomeBack", { username: me.username })}
          </Heading>
          <Text mt="3" maxW="620px" color="fg.muted">
            {active
              ? t("portal.overviewSubtitleActive")
              : me.usage.status === "on_hold"
              ? t("portal.overviewSubtitleOnHold")
              : me.subscription
              ? t("portal.overviewSubtitleInactive")
              : t("portal.overviewSubtitleEmpty")}
          </Text>
          <HStack mt="7" spacing="3" flexWrap="wrap">
            <Button
              colorScheme="primary"
              onClick={() => navigate("/portal/access")}
              isDisabled={!canIssueMgma}
            >
              {t("portal.getMgma")}
            </Button>
            <Button variant="outline" onClick={() => navigate("/portal/plans")}>
              {t("portal.browsePlans")}
            </Button>
          </HStack>
        </Box>

        <Card variant="glass" rounded="3xl">
          <CardBody p={{ base: 6, md: 7 }}>
            <Text color="fg.subtle" fontSize="sm">
              {t("portal.currentPlan")}
            </Text>
            <Heading mt="2" size="md">
              {me.subscription?.plan_name || t("portal.noPlan")}
            </Heading>
            {me.subscription ? (
              <VStack mt="6" align="stretch" spacing="4">
                <HStack justify="space-between">
                  <Text color="fg.muted">{t("portal.expiresAt")}</Text>
                  <Text fontWeight="600">
                    {dayjs(me.subscription.expires_at).format("YYYY-MM-DD")}
                  </Text>
                </HStack>
                <HStack justify="space-between">
                  <Text color="fg.muted">{t("portal.planDuration")}</Text>
                  <Text fontWeight="600">
                    {me.subscription.duration_days} {t("portal.days")}
                  </Text>
                </HStack>
              </VStack>
            ) : (
              <Text mt="5" color="fg.muted">
                {t("portal.noPlanHelp")}
              </Text>
            )}
          </CardBody>
        </Card>
      </Grid>

      <SimpleGrid columns={{ base: 1, md: 3 }} spacing="4">
        <Card variant="glass">
          <CardBody>
            <Stat>
              <StatLabel>{t("portal.walletBalance")}</StatLabel>
              <StatNumber>{money(me.wallet_balance_minor)}</StatNumber>
            </Stat>
          </CardBody>
        </Card>
        <Card variant="glass">
          <CardBody>
            <Stat>
              <StatLabel>{t("portal.trafficUsage")}</StatLabel>
              <StatNumber fontSize="xl">
                {formatBytes(me.usage.used_traffic)}
              </StatNumber>
            </Stat>
          </CardBody>
        </Card>
        <Card variant="glass">
          <CardBody>
            <Stat>
              <StatLabel>{t("portal.accountStatus")}</StatLabel>
              <StatNumber fontSize="xl">
                {me.usage.status
                  ? t(`status.${me.usage.status}`)
                  : t("portal.notActivated")}
              </StatNumber>
            </Stat>
          </CardBody>
        </Card>
      </SimpleGrid>

      <Card variant="glass" rounded="3xl">
        <CardBody p={{ base: 6, md: 7 }}>
          <HStack justify="space-between" align="start" mb="5" flexWrap="wrap">
            <Box>
              <Heading size="md">{t("portal.trafficUsage")}</Heading>
              <Text mt="1" color="fg.muted" fontSize="sm">
                {t("portal.trafficUsageHelp")}
              </Text>
            </Box>
            <Text fontWeight="700">
              {formatBytes(me.usage.used_traffic)} /{" "}
              {limit ? formatBytes(limit) : t("portal.unlimited")}
            </Text>
          </HStack>
          <Progress
            aria-label={t("portal.trafficUsage")}
            value={percent}
            colorScheme={percent >= 90 ? "red" : "primary"}
            rounded="full"
            h="3"
            bg="surface.track"
          />
          <Text mt="4" fontSize="sm" color="fg.muted">
            {t("portal.lifetimeUsage")}:{" "}
            {formatBytes(me.usage.lifetime_used_traffic)}
          </Text>
        </CardBody>
      </Card>
    </VStack>
  );
};
