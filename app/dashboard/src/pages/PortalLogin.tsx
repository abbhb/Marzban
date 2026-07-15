import {
  Alert,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  HStack,
  Link,
  Text,
  VStack,
} from "@chakra-ui/react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Footer } from "components/Footer";
import { Input } from "components/Input";
import { Language } from "components/Language";
import { useEffect, useState } from "react";
import { FieldValues, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { portalFetch } from "service/http";
import {
  removePortalAuthToken,
  setPortalAuthToken,
} from "utils/portalAuthStorage";
import { z } from "zod";
import { LogoIcon } from "./Login";

const schema = z.object({
  username: z.string().min(1, "login.fieldRequired"),
  password: z.string().min(1, "login.fieldRequired"),
});

const errorDetail = (error: any): string =>
  error?.data?.detail || error?.response?._data?.detail || "portal.requestFailed";

export const PortalLogin = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: zodResolver(schema) });

  useEffect(() => removePortalAuthToken(), []);

  const login = (values: FieldValues) => {
    const body = new FormData();
    body.append("username", values.username);
    body.append("password", values.password);
    body.append("grant_type", "password");
    setError("");
    setLoading(true);
    portalFetch<{ access_token: string }>("/portal/token", {
      method: "POST",
      body,
    })
      .then(({ access_token }) => {
        setPortalAuthToken(access_token);
        navigate("/portal");
      })
      .catch((err) => setError(errorDetail(err)))
      .finally(() => setLoading(false));
  };

  return (
    <VStack as="main" justifyContent="space-between" minH="100vh" p="6" w="full">
      <Box w="full">
        <HStack justifyContent="end"><Language /></HStack>
        <VStack maxW="360px" mx="auto" mt="10" spacing="5">
          <LogoIcon />
          <Text fontSize="2xl" fontWeight="semibold">{t("portal.loginTitle")}</Text>
          <Text color="gray.500">{t("portal.loginSubtitle")}</Text>
          <Box as="form" w="full" onSubmit={handleSubmit(login)}>
            <VStack spacing="3">
              <Input
                placeholder={t("username")}
                autoComplete="username"
                {...register("username")}
                error={t(errors.username?.message as string)}
              />
              <Input
                type="password"
                placeholder={t("password")}
                autoComplete="current-password"
                {...register("password")}
                error={t(errors.password?.message as string)}
              />
              {error && (
                <Alert status="error" rounded="md">
                  <AlertIcon />
                  <AlertDescription>{t(error)}</AlertDescription>
                </Alert>
              )}
              <Button type="submit" colorScheme="primary" w="full" isLoading={loading}>
                {t("portal.login")}
              </Button>
            </VStack>
          </Box>
          <HStack fontSize="sm">
            <Text>{t("portal.noAccount")}</Text>
            <Link as={RouterLink} to="/portal/register" color="primary.500">
              {t("portal.register")}
            </Link>
          </HStack>
          <Link as={RouterLink} to="/login" fontSize="sm" color="gray.500">
            {t("portal.adminLogin")}
          </Link>
        </VStack>
      </Box>
      <Footer />
    </VStack>
  );
};
