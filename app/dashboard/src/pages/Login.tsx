import {
  Alert,
  AlertDescription,
  AlertIcon,
  Button,
  chakra,
  Link,
  Text,
  VStack,
} from "@chakra-ui/react";
import { ArrowRightOnRectangleIcon } from "@heroicons/react/24/outline";
import { zodResolver } from "@hookform/resolvers/zod";
import { FC, useEffect, useState } from "react";
import { FieldValues, useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";
import { Link as RouterLink } from "react-router-dom";
import { z } from "zod";
import { AuthShell } from "components/AuthShell";
import { Input } from "components/Input";
import { fetch } from "service/http";
import { removeAuthToken, setAuthToken } from "utils/authStorage";
import { useTranslation } from "react-i18next";

const schema = z.object({
  username: z.string().min(1, "login.fieldRequired"),
  password: z.string().min(1, "login.fieldRequired"),
});

export { LogoIcon } from "components/AuthShell";

const LoginIcon = chakra(ArrowRightOnRectangleIcon, {
  baseStyle: {
    w: 5,
    h: 5,
    strokeWidth: "2px",
  },
});

export const Login: FC = () => {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation();
  let location = useLocation();
  const {
    register,
    formState: { errors },
    handleSubmit,
  } = useForm({
    resolver: zodResolver(schema),
  });
  useEffect(() => {
    removeAuthToken();
    if (location.pathname !== "/login/admin") {
      navigate("/login/admin", { replace: true });
    }
  }, []);
  const login = (values: FieldValues) => {
    setError("");
    const formData = new FormData();
    formData.append("username", values.username);
    formData.append("password", values.password);
    formData.append("grant_type", "password");
    setLoading(true);
    fetch("/admin/token", { method: "post", body: formData })
      .then(({ access_token: token }) => {
        setAuthToken(token);
        navigate("/");
      })
      .catch((err) => {
        setError(err.response._data.detail);
      })
      .finally(setLoading.bind(null, false));
  };
  return (
    <AuthShell
      context="admin"
      title={t("login.loginYourAccount")}
      subtitle={t("login.welcomeBack")}
      footer={
        <Text textAlign="center">
          <Link
            as={RouterLink}
            to="/login"
            color="primary.500"
            fontWeight="600"
          >
            {t("portal.userLogin")}
          </Link>
        </Text>
      }
    >
      <form onSubmit={handleSubmit(login)}>
        <VStack spacing="3">
          <Input
            w="full"
            label={t("username")}
            placeholder={t("username")}
            autoComplete="username"
            {...register("username")}
            error={t(errors?.username?.message as string)}
          />
          <Input
            w="full"
            type="password"
            label={t("password")}
            placeholder={t("password")}
            autoComplete="current-password"
            {...register("password")}
            error={t(errors?.password?.message as string)}
          />
          {error && (
            <Alert status="error" rounded="xl">
              <AlertIcon />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button
            isLoading={loading}
            type="submit"
            w="full"
            minH="12"
            colorScheme="primary"
          >
            <LoginIcon marginRight={1} />
            {t("login")}
          </Button>
        </VStack>
      </form>
    </AuthShell>
  );
};

export default Login;
