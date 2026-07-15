import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Card,
  CardBody,
  Heading,
  HStack,
  Spinner,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
} from "@chakra-ui/react";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import { usePortalContext } from "./PortalLayout";

const money = (minor: number): string => `¥${(minor / 100).toFixed(2)}`;
const signedMoney = (minor: number): string =>
  `${minor > 0 ? "+" : minor < 0 ? "-" : ""}¥${(Math.abs(minor) / 100).toFixed(
    2
  )}`;

export const PortalWallet = () => {
  const { me, transactions, transactionsError, supplementalLoading, refresh } =
    usePortalContext();
  const { t } = useTranslation();

  return (
    <VStack align="stretch" spacing="6">
      <Box
        layerStyle="glassHero"
        className="glass-surface"
        rounded="3xl"
        p={{ base: 6, md: 8 }}
      >
        <Text color="fg.muted">{t("portal.walletBalance")}</Text>
        <Heading mt="2" size="2xl" letterSpacing="-.05em">
          {money(me.wallet_balance_minor)}
        </Heading>
        <Text mt="3" color="fg.muted" fontSize="sm">
          {t("portal.walletHelp")}
        </Text>
      </Box>
      <Box>
        <Heading size="md">{t("portal.walletHistory")}</Heading>
        <Text mt="1" color="fg.muted" fontSize="sm">
          {t("portal.walletHistoryHelp")}
        </Text>
      </Box>
      {transactionsError && (
        <Alert status="error" rounded="2xl" alignItems="center">
          <AlertIcon />
          <AlertDescription flex="1">
            {t("portal.dataLoadError")}
          </AlertDescription>
          <Button
            size="sm"
            variant="outline"
            colorScheme="red"
            onClick={refresh}
          >
            {t("portal.retry")}
          </Button>
        </Alert>
      )}
      {supplementalLoading && !transactions.length ? (
        <VStack py="16">
          <Spinner color="primary.500" />
        </VStack>
      ) : transactionsError &&
        !transactions.length ? null : !transactions.length ? (
        <Card variant="glass">
          <CardBody py="14" textAlign="center">
            <Text color="fg.muted">{t("portal.noTransactions")}</Text>
          </CardBody>
        </Card>
      ) : (
        <>
          <Card
            variant="glass"
            display={{ base: "none", md: "block" }}
            overflow="hidden"
          >
            <CardBody p="0">
              <TableContainer>
                <Table>
                  <Thead>
                    <Tr>
                      <Th>{t("portal.time")}</Th>
                      <Th>{t("portal.type")}</Th>
                      <Th isNumeric>{t("portal.amount")}</Th>
                      <Th isNumeric>{t("portal.balanceAfter")}</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {transactions.map((item) => (
                      <Tr key={item.id}>
                        <Td>
                          {dayjs(item.created_at).format("YYYY-MM-DD HH:mm")}
                        </Td>
                        <Td>{t(`portal.transaction.${item.kind}`)}</Td>
                        <Td
                          isNumeric
                          color={
                            item.amount_minor > 0 ? "green.500" : "red.500"
                          }
                          fontWeight="700"
                        >
                          {signedMoney(item.amount_minor)}
                        </Td>
                        <Td isNumeric>{money(item.balance_after_minor)}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </TableContainer>
            </CardBody>
          </Card>
          <VStack
            display={{ base: "flex", md: "none" }}
            align="stretch"
            spacing="3"
          >
            {transactions.map((item) => (
              <Card key={item.id} variant="glass">
                <CardBody>
                  <HStack justify="space-between" align="start">
                    <Box>
                      <Text fontWeight="700">
                        {t(`portal.transaction.${item.kind}`)}
                      </Text>
                      <Text mt="1" fontSize="xs" color="fg.subtle">
                        {dayjs(item.created_at).format("YYYY-MM-DD HH:mm")}
                      </Text>
                    </Box>
                    <Badge
                      colorScheme={item.amount_minor > 0 ? "green" : "red"}
                      fontSize="sm"
                    >
                      {signedMoney(item.amount_minor)}
                    </Badge>
                  </HStack>
                  <HStack mt="4" justify="space-between">
                    <Text fontSize="sm" color="fg.muted">
                      {t("portal.balanceAfter")}
                    </Text>
                    <Text fontWeight="600">
                      {money(item.balance_after_minor)}
                    </Text>
                  </HStack>
                </CardBody>
              </Card>
            ))}
          </VStack>
        </>
      )}
    </VStack>
  );
};
