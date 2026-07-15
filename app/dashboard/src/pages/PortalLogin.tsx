import {
  Alert,
  AlertDescription,
  AlertIcon,
  Button,
  HStack,
  Link,
  Text,
  VStack,
} from "@chakra-ui/react";
import { zodResolver } from "@hookform/resolvers/zod";
import { AuthShell } from "components/AuthShell";
import { Input } from "components/Input";
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

const schema = z.object({
  username: z.string().min(1, "login.fieldRequired"),
  password: z.string().min(1, "login.fieldRequired"),
});

const errorDetail = (error: any): string =>
  error?.data?.detail ||
  error?.response?._data?.detail ||
  "portal.requestFailed";

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
    <AuthShell
      title={t("portal.loginTitle")}
      subtitle={t("portal.loginSubtitle")}
      footer={
        <>
          <HStack justify="center" flexWrap="wrap">
            <Text>{t("portal.noAccount")}</Text>
            <Link
              as={RouterLink}
              to="/portal/register"
              color="primary.500"
              fontWeight="600"
            >
              {t("portal.register")}
            </Link>
          </HStack>
          <Link
            as={RouterLink}
            to="/login"
            textAlign="center"
            color="fg.subtle"
          >
            {t("portal.adminLogin")}
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(login)}>
        <VStack spacing="3">
          <Input
            label={t("username")}
            placeholder={t("username")}
            autoComplete="username"
            {...register("username")}
            error={t(errors.username?.message as string)}
          />
          <Input
            type="password"
            label={t("password")}
            placeholder={t("password")}
            autoComplete="current-password"
            {...register("password")}
            error={t(errors.password?.message as string)}
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
            w="full"
            minH="12"
            isLoading={loading}
          >
            {t("portal.login")}
          </Button>
        </VStack>
      </form>
    </AuthShell>
  );
};
