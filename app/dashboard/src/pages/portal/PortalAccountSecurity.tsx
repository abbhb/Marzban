import { errorMessage } from "service/http";
import {
  Alert,
  AlertDescription,
  AlertIcon,
  Button,
  Card,
  CardBody,
  Heading,
  Text,
  VisuallyHidden,
  VStack,
} from "@chakra-ui/react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Input } from "components/Input";
import { useState } from "react";
import { FieldValues, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { portalFetch } from "service/http";
import { removePortalAuthToken } from "utils/portalAuthStorage";
import { z } from "zod";
import { usePortalContext } from "./PortalLayout";

const schema = z
  .object({
    currentPassword: z.string().min(1, "login.fieldRequired"),
    newPassword: z
      .string()
      .min(10, "portal.passwordLength")
      .max(128, "portal.passwordLength"),
    confirmPassword: z.string(),
  })
  .refine((values) => values.newPassword === values.confirmPassword, {
    path: ["confirmPassword"],
    message: "portal.passwordMismatch",
  });

export const PortalAccountSecurity = () => {
  const { t } = useTranslation();
  const { me } = usePortalContext();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: zodResolver(schema) });

  const submit = (values: FieldValues) => {
    setError("");
    setLoading(true);
    portalFetch("/portal/password/change", {
      method: "POST",
      body: {
        current_password: values.currentPassword,
        new_password: values.newPassword,
      },
    })
      .then(() => {
        removePortalAuthToken();
        navigate("/login", { replace: true, state: { passwordChanged: true } });
      })
      .catch((requestError: any) =>
        setError(
          errorMessage(requestError, "portal.requestFailed")
        )
      )
      .finally(() => setLoading(false));
  };

  return (
    <Card variant="glass" rounded="3xl" maxW="720px">
      <CardBody p={{ base: 6, md: 8 }}>
        <Heading size="md">{t("portal.changePassword")}</Heading>
        <Text mt="2" color="fg.muted">
          {t("portal.changePasswordHelp")}
        </Text>
        <form onSubmit={handleSubmit(submit)}>
          <VisuallyHidden>
            <input
              type="text"
              name="username"
              autoComplete="username"
              value={me.username}
              readOnly
              tabIndex={-1}
            />
          </VisuallyHidden>
          <VStack mt="6" spacing="4" align="stretch">
            <Input
              type="password"
              autoComplete="current-password"
              label={t("portal.currentPassword")}
              {...register("currentPassword")}
              error={t(errors.currentPassword?.message as string)}
            />
            <Input
              type="password"
              autoComplete="new-password"
              label={t("portal.newPassword")}
              {...register("newPassword")}
              error={t(errors.newPassword?.message as string)}
            />
            <Input
              type="password"
              autoComplete="new-password"
              label={t("portal.confirmPassword")}
              {...register("confirmPassword")}
              error={t(errors.confirmPassword?.message as string)}
            />
            {error && (
              <Alert status="error" rounded="xl">
                <AlertIcon />
                <AlertDescription>{t(error)}</AlertDescription>
              </Alert>
            )}
            <Button
              type="submit"
              colorScheme="primary"
              alignSelf="flex-start"
              minW="160px"
              isLoading={loading}
            >
              {t("portal.updatePassword")}
            </Button>
          </VStack>
        </form>
      </CardBody>
    </Card>
  );
};
