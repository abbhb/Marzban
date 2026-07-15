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
import { useState } from "react";
import { FieldValues, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import { portalFetch } from "service/http";
import { z } from "zod";
import { LogoIcon } from "./Login";

const schema = z
  .object({
    invitationCode: z.string().min(20, "portal.invitationRequired").max(128, "portal.invitationRequired"),
    username: z.string().min(3, "portal.usernameLength").max(32, "portal.usernameLength"),
    password: z.string().min(10, "portal.passwordLength").max(128, "portal.passwordLength"),
    confirmPassword: z.string(),
  })
  .refine((values) => values.password === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "portal.passwordMismatch",
  });

export const PortalRegister = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: zodResolver(schema) });

  const submit = (values: FieldValues) => {
    setError("");
    setLoading(true);
    portalFetch("/portal/register", {
      method: "POST",
      body: {
        username: values.username,
        password: values.password,
        invitation_code: values.invitationCode.trim(),
      },
    })
      .then(() => navigate("/portal/login", { state: { registered: true } }))
      .catch((err: any) =>
        setError(err?.data?.detail || err?.response?._data?.detail || "portal.requestFailed")
      )
      .finally(() => setLoading(false));
  };

  return (
    <VStack as="main" justifyContent="space-between" minH="100vh" p="6" w="full">
      <Box w="full">
        <HStack justifyContent="end"><Language /></HStack>
        <VStack maxW="360px" mx="auto" mt="8" spacing="5">
          <LogoIcon />
          <Text fontSize="2xl" fontWeight="semibold">{t("portal.registerTitle")}</Text>
          <Text color="gray.500">{t("portal.registerSubtitle")}</Text>
          <Box as="form" w="full" onSubmit={handleSubmit(submit)}>
            <VStack spacing="3">
              <Input autoComplete="off" placeholder={t("portal.invitationCode")} {...register("invitationCode")} error={t(errors.invitationCode?.message as string)} />
              <Input autoComplete="username" placeholder={t("username")} {...register("username")} error={t(errors.username?.message as string)} />
              <Input autoComplete="new-password" type="password" placeholder={t("password")} {...register("password")} error={t(errors.password?.message as string)} />
              <Input autoComplete="new-password" type="password" placeholder={t("portal.confirmPassword")} {...register("confirmPassword")} error={t(errors.confirmPassword?.message as string)} />
              {error && (
                <Alert status="error" rounded="md"><AlertIcon /><AlertDescription>{t(error)}</AlertDescription></Alert>
              )}
              <Button type="submit" colorScheme="primary" w="full" isLoading={loading}>
                {t("portal.createAccount")}
              </Button>
            </VStack>
          </Box>
          <HStack fontSize="sm">
            <Text>{t("portal.haveAccount")}</Text>
            <Link as={RouterLink} to="/portal/login" color="primary.500">{t("portal.login")}</Link>
          </HStack>
        </VStack>
      </Box>
      <Footer />
    </VStack>
  );
};
