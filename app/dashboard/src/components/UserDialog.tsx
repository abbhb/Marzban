import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  ButtonGroup,
  Collapse,
  Flex,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  Grid,
  GridItem,
  HStack,
  IconButton,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Spinner,
  Switch,
  Text,
  Textarea,
  Tooltip,
  VStack,
  chakra,
  useColorMode,
  useToast,
} from "@chakra-ui/react";
import {
  ChartPieIcon,
  CheckCircleIcon,
  NoSymbolIcon,
  PencilIcon,
  UserPlusIcon,
} from "@heroicons/react/24/outline";
import { zodResolver } from "@hookform/resolvers/zod";
import { resetStrategy } from "constants/UserSettings";
import { FilterUsageType, useDashboard } from "contexts/DashboardContext";
import dayjs from "dayjs";
import { FC, useEffect, useState } from "react";
import ReactApexChart from "react-apexcharts";
import ReactDatePicker from "react-datepicker";
import { Controller, FormProvider, useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import {
  ProxyKeys,
  ProxyType,
  User,
  UserApi,
  UserCreate,
  UserEntitlement,
  UserInbounds,
  UserModify,
} from "types/User";
import {
  GeneratedPassword,
  ManagedAccountCreation,
  SubscriptionPlan,
} from "types/Commerce";
import { relativeExpiryDate } from "utils/dateFormatter";
import { z } from "zod";
import { DeleteIcon } from "./DeleteUserModal";
import { Icon } from "./Icon";
import { Input } from "./Input";
import { RadioGroup } from "./RadioGroup";
import { UsageFilter, createUsageConfig } from "./UsageFilter";
import { ReloadIcon } from "./Filters";
import classNames from "classnames";
import { useLoaderData, useNavigate } from "react-router-dom";
import { fetch as apiFetch } from "service/http";
import "./datePickerSetup";
import { OneTimePasswordPanel } from "./OneTimePasswordPanel";

const AddUserIcon = chakra(UserPlusIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

const EditUserIcon = chakra(PencilIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

const UserUsageIcon = chakra(ChartPieIcon, {
  baseStyle: {
    w: 5,
    h: 5,
  },
});

export type UserDialogProps = {};

export type FormType = Pick<UserCreate, keyof UserCreate> & {
  selected_proxies: ProxyKeys;
};

const formatUser = (user: User): FormType => {
  return {
    ...user,
    data_limit: user.data_limit
      ? Number((user.data_limit / 1073741824).toFixed(5))
      : user.data_limit,
    on_hold_expire_duration: user.on_hold_expire_duration
      ? Number(user.on_hold_expire_duration / (24 * 60 * 60))
      : user.on_hold_expire_duration,
    selected_proxies: Object.keys(user.proxies) as ProxyKeys,
  };
};
const getDefaultValues = (): FormType => {
  const defaultInbounds = Object.fromEntries(useDashboard.getState().inbounds);
  const inbounds: UserInbounds = {};
  for (const key in defaultInbounds) {
    inbounds[key] = defaultInbounds[key].map((i) => i.tag);
  }
  return {
    selected_proxies: Object.keys(defaultInbounds) as ProxyKeys,
    data_limit: null,
    expire: null,
    username: "",
    data_limit_reset_strategy: "no_reset",
    status: "active",
    on_hold_expire_duration: null,
    note: "",
    inbounds,
    proxies: {
      vless: { id: "", flow: "" },
      vmess: { id: "" },
      trojan: { password: "" },
      shadowsocks: { password: "", method: "chacha20-ietf-poly1305" },
    },
  };
};

const mergeProxies = (
  proxyKeys: ProxyKeys,
  proxyType: ProxyType | undefined
): ProxyType => {
  const proxies: ProxyType = proxyKeys.reduce(
    (ac, a) => ({ ...ac, [a]: {} }),
    {}
  );
  if (!proxyType) return proxies;
  proxyKeys.forEach((proxy) => {
    if (proxyType[proxy]) {
      proxies[proxy] = proxyType[proxy];
    }
  });
  return proxies;
};

const baseSchema = {
  username: z.string().min(1, { message: "Required" }),
  selected_proxies: z.array(z.string()).refine((value) => value.length > 0, {
    message: "userDialog.selectOneProtocol",
  }),
  note: z.string().nullable(),
  proxies: z
    .record(z.string(), z.record(z.string(), z.any()))
    .transform((ins) => {
      const deleteIfEmpty = (obj: any, key: string) => {
        if (obj && obj[key] === "") {
          delete obj[key];
        }
      };
      deleteIfEmpty(ins.vmess, "id");
      deleteIfEmpty(ins.vless, "id");
      deleteIfEmpty(ins.trojan, "password");
      deleteIfEmpty(ins.shadowsocks, "password");
      deleteIfEmpty(ins.shadowsocks, "method");
      return ins;
    }),
  data_limit: z
    .string()
    .min(0)
    .or(z.number())
    .nullable()
    .transform((str) => {
      if (str) return Number((parseFloat(String(str)) * 1073741824).toFixed(5));
      return 0;
    }),
  expire: z.number().nullable(),
  data_limit_reset_strategy: z.string(),
  inbounds: z.record(z.string(), z.array(z.string())).transform((ins) => {
    Object.keys(ins).forEach((protocol) => {
      if (Array.isArray(ins[protocol]) && !ins[protocol]?.length)
        delete ins[protocol];
    });
    return ins;
  }),
};

const schema = z.discriminatedUnion("status", [
  z.object({
    status: z.literal("active"),
    ...baseSchema,
  }),
  z.object({
    status: z.literal("disabled"),
    ...baseSchema,
  }),
  z.object({
    status: z.literal("limited"),
    ...baseSchema,
  }),
  z.object({
    status: z.literal("expired"),
    ...baseSchema,
  }),
  z.object({
    status: z.literal("on_hold"),
    on_hold_expire_duration: z.coerce
      .number()
      .min(0.1, "Required")
      .transform((d) => {
        return d * (24 * 60 * 60);
      }),
    ...baseSchema,
  }),
]);

export const UserDialog: FC<UserDialogProps> = () => {
  const {
    editingUser,
    isCreatingNewUser,
    onCreateUser,
    editUser,
    fetchUserUsage,
    onEditingUser,
    createUser,
    onDeletingUser,
    refetchUsers,
  } = useDashboard();
  const isEditing = !!editingUser;
  const isOpen = isCreatingNewUser || isEditing;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>("");
  const toast = useToast();
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const adminUser = useLoaderData() as UserApi;
  const [creationMode, setCreationMode] = useState<"managed" | "manual">(
    adminUser.is_sudo ? "managed" : "manual"
  );
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [plansError, setPlansError] = useState(false);
  const [planId, setPlanId] = useState("");
  const [generatedPassword, setGeneratedPassword] =
    useState<GeneratedPassword | null>(null);

  const { colorMode } = useColorMode();

  const [usageVisible, setUsageVisible] = useState(false);
  const [entitlement, setEntitlement] = useState<UserEntitlement | null>(null);
  const [entitlementLoading, setEntitlementLoading] = useState(false);
  const [entitlementError, setEntitlementError] = useState(false);
  const handleUsageToggle = () => {
    setUsageVisible((current) => !current);
  };

  const form = useForm<FormType>({
    defaultValues: getDefaultValues(),
    resolver: zodResolver(schema),
  });

  const [dataLimit, userStatus] = useWatch({
    control: form.control,
    name: ["data_limit", "status"],
  });

  const usageTitle = t("userDialog.total");
  const [usage, setUsage] = useState(createUsageConfig(colorMode, usageTitle));
  const [usageFilter, setUsageFilter] = useState("1m");
  const fetchUsageWithFilter = (query: FilterUsageType) => {
    fetchUserUsage(editingUser!, query).then((data: any) => {
      const labels = [];
      const series = [];
      for (const key in data.usages) {
        series.push(data.usages[key].used_traffic);
        labels.push(data.usages[key].node_name);
      }
      setUsage(createUsageConfig(colorMode, usageTitle, series, labels));
    });
  };

  useEffect(() => {
    if (editingUser) {
      form.reset(formatUser(editingUser));

      fetchUsageWithFilter({
        start: dayjs().utc().subtract(30, "day").format("YYYY-MM-DDTHH:00:00"),
      });
    }
  }, [editingUser]);

  useEffect(() => {
    if (!isCreatingNewUser || !adminUser.is_sudo || creationMode !== "managed")
      return;
    const controller = new AbortController();
    setPlansLoading(true);
    setPlansError(false);
    apiFetch<SubscriptionPlan[]>("/commerce/admin/plans", {
      signal: controller.signal,
    })
      .then((items) => {
        setPlans(items);
        setPlanId((current) => {
          if (current && items.some((plan) => String(plan.id) === current))
            return current;
          const preferred = items.find((plan) => plan.is_visible) || items[0];
          return preferred ? String(preferred.id) : "";
        });
      })
      .catch((requestError: any) => {
        if (requestError?.name !== "AbortError") setPlansError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setPlansLoading(false);
      });
    return () => controller.abort();
  }, [adminUser.is_sudo, creationMode, isCreatingNewUser]);

  useEffect(() => {
    if (!editingUser) {
      setEntitlement(null);
      setEntitlementLoading(false);
      setEntitlementError(false);
      return;
    }

    const controller = new AbortController();
    setEntitlement(null);
    setEntitlementLoading(true);
    setEntitlementError(false);
    apiFetch<UserEntitlement>(
      `/user/${encodeURIComponent(editingUser.username)}/entitlement`,
      { signal: controller.signal }
    )
      .then(setEntitlement)
      .catch((requestError: any) => {
        if (requestError?.name !== "AbortError") setEntitlementError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setEntitlementLoading(false);
      });
    return () => controller.abort();
  }, [editingUser]);

  const submit = (values: FormType) => {
    setLoading(true);
    setError(null);

    if (!isEditing && creationMode === "managed") {
      if (!planId) {
        setError(t("userDialog.selectPlanRequired"));
        setLoading(false);
        return;
      }
      apiFetch<ManagedAccountCreation>("/commerce/admin/accounts", {
        method: "POST",
        body: {
          username: values.username,
          plan_id: Number(planId),
        },
      })
        .then((result) => {
          setGeneratedPassword({
            username: result.username,
            password: result.password,
          });
          refetchUsers();
        })
        .catch((err: any) => {
          setError(
            err?.data?.detail ||
              err?.response?._data?.detail ||
              t("userDialog.managedCreateError")
          );
        })
        .finally(() => setLoading(false));
      return;
    }

    const { selected_proxies, ...rest } = values;

    let body: UserCreate | UserModify = {
      ...rest,
      data_limit: values.data_limit,
      proxies: mergeProxies(selected_proxies, values.proxies),
      data_limit_reset_strategy:
        values.data_limit && values.data_limit > 0
          ? values.data_limit_reset_strategy
          : "no_reset",
      status:
        values.status === "active" ||
        values.status === "disabled" ||
        values.status === "on_hold"
          ? values.status
          : "active",
    };

    if (isEditing && entitlement?.managed_by_plan) {
      const {
        proxies: _proxies,
        inbounds: _inbounds,
        ...planManagedBody
      } = body;
      body = planManagedBody;
    }

    const request = isEditing
      ? editUser(body as UserModify)
      : createUser(body as UserCreate);

    request
      .then(() => {
        toast({
          title: t(
            isEditing ? "userDialog.userEdited" : "userDialog.userCreated",
            { username: values.username }
          ),
          status: "success",
          isClosable: true,
          position: "top",
          duration: 3000,
        });
        onClose();
      })
      .catch((err) => {
        if (err?.response?.status === 409 || err?.response?.status === 400)
          setError(err?.response?._data?.detail);
        if (err?.response?.status === 422) {
          Object.keys(err.response._data.detail).forEach((key) => {
            setError(err?.response._data.detail[key] as string);
            form.setError(
              key as "proxies" | "username" | "data_limit" | "expire",
              {
                type: "custom",
                message: err.response._data.detail[key],
              }
            );
          });
        }
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const onClose = () => {
    form.reset(getDefaultValues());
    onCreateUser(false);
    onEditingUser(null);
    setError(null);
    setUsageVisible(false);
    setUsageFilter("1m");
    setEntitlement(null);
    setEntitlementLoading(false);
    setEntitlementError(false);
    setCreationMode(adminUser.is_sudo ? "managed" : "manual");
    setPlans([]);
    setPlansLoading(false);
    setPlansError(false);
    setPlanId("");
    setGeneratedPassword(null);
  };

  const handleResetUsage = () => {
    useDashboard.setState({ resetUsageUser: editingUser });
  };

  const handleRevokeSubscription = () => {
    useDashboard.setState({ revokeSubscriptionUser: editingUser });
  };

  const handleStatusAction = () => {
    form.setValue("status", userStatus === "active" ? "disabled" : "active", {
      shouldDirty: true,
    });
    void form.handleSubmit(submit)();
  };

  const handleResetPassword = () => {
    if (!entitlement?.account_id) return;
    setLoading(true);
    setError(null);
    apiFetch<GeneratedPassword>(
      `/commerce/admin/accounts/${entitlement.account_id}/password/reset`,
      { method: "POST" }
    )
      .then(setGeneratedPassword)
      .catch((err: any) =>
        setError(
          err?.data?.detail ||
            err?.response?._data?.detail ||
            t("userDialog.passwordResetError")
        )
      )
      .finally(() => setLoading(false));
  };

  const disabled = loading || entitlementLoading;
  const submitDisabled = disabled || (isEditing && entitlementError);
  const isOnHold = userStatus === "on_hold";

  const [randomUsernameLoading, setrandomUsernameLoading] = useState(false);

  const createRandomUsername = (): string => {
    setrandomUsernameLoading(true);
    let result = "";
    const characters =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    const charactersLength = characters.length;
    let counter = 0;
    while (counter < 6) {
      result += characters.charAt(Math.floor(Math.random() * charactersLength));
      counter += 1;
    }
    return result;
  };

  const openPlanManagement = () => {
    if (!entitlement?.account_id) return;
    const accountId = entitlement.account_id;
    onClose();
    navigate(`/commerce?tab=accounts&account=${accountId}`);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="2xl">
      <ModalOverlay
        bg="blackAlpha.300"
        backdropFilter="var(--marzban-overlay-filter)"
      />
      <FormProvider {...form}>
        <ModalContent mx="3">
          <form onSubmit={form.handleSubmit(submit)}>
            <ModalHeader pt={6}>
              <HStack gap={2}>
                <Icon color="primary">
                  {isEditing ? (
                    <EditUserIcon color="white" />
                  ) : (
                    <AddUserIcon color="white" />
                  )}
                </Icon>
                <Text fontWeight="semibold" fontSize="lg">
                  {generatedPassword
                    ? t("userDialog.credentialsReady")
                    : isEditing
                    ? t("userDialog.editUserTitle")
                    : t("createNewUser")}
                </Text>
              </HStack>
            </ModalHeader>
            <ModalCloseButton disabled={loading} />
            <ModalBody>
              {generatedPassword ? (
                <OneTimePasswordPanel {...generatedPassword} />
              ) : (
                <>
                  {!isEditing && adminUser.is_sudo && (
                    <ButtonGroup
                      isAttached
                      size="sm"
                      mb="5"
                      p="1"
                      rounded="xl"
                      bg="surface.inset"
                    >
                      <Button
                        type="button"
                        colorScheme={
                          creationMode === "managed" ? "primary" : "gray"
                        }
                        variant={
                          creationMode === "managed" ? "solid" : "ghost"
                        }
                        onClick={() => setCreationMode("managed")}
                      >
                        {t("userDialog.planManagedCreation")}
                      </Button>
                      <Button
                        type="button"
                        colorScheme={
                          creationMode === "manual" ? "primary" : "gray"
                        }
                        variant={creationMode === "manual" ? "solid" : "ghost"}
                        onClick={() => setCreationMode("manual")}
                      >
                        {t("userDialog.manualCreation")}
                      </Button>
                    </ButtonGroup>
                  )}
                  {!isEditing && creationMode === "managed" ? (
                    <VStack align="stretch" spacing="5">
                      <Alert status="info" alignItems="flex-start" rounded="2xl">
                        <AlertIcon mt="0.5" />
                        <Box>
                          <Text fontWeight="800">
                            {t("userDialog.planManagedCreation")}
                          </Text>
                          <Text mt="1" fontSize="sm">
                            {t("userDialog.planManagedCreationHelp")}
                          </Text>
                        </Box>
                      </Alert>
                      <FormControl
                        isInvalid={!!form.formState.errors.username?.message}
                      >
                        <FormLabel>
                          <Flex gap="2" align="center">
                            {t("username")}
                            <ReloadIcon
                              cursor="pointer"
                              className={classNames({
                                "animate-spin": randomUsernameLoading,
                              })}
                              onClick={() => {
                                form.setValue("username", createRandomUsername(), {
                                  shouldValidate: true,
                                });
                                setTimeout(
                                  () => setrandomUsernameLoading(false),
                                  350
                                );
                              }}
                            />
                          </Flex>
                        </FormLabel>
                        <Input
                          autoComplete="off"
                          {...form.register("username")}
                          error={form.formState.errors.username?.message}
                        />
                      </FormControl>
                      <FormControl isInvalid={!planId && !!error}>
                        <FormLabel>{t("portal.currentPlan")}</FormLabel>
                        <Select
                          value={planId}
                          onChange={(event) => setPlanId(event.target.value)}
                          isDisabled={plansLoading || plansError}
                        >
                          <option value="">
                            {t(
                              plansLoading
                                ? "hostsDialog.loading"
                                : "commerce.selectPlan"
                            )}
                          </option>
                          {plans.map((plan) => (
                            <option key={plan.id} value={plan.id}>
                              {plan.name}
                              {!plan.is_visible
                                ? ` (${t("commerce.hidden")})`
                                : ""}
                            </option>
                          ))}
                        </Select>
                        <FormHelperText>
                          {t("userDialog.planControlsEntitlements")}
                        </FormHelperText>
                      </FormControl>
                      {plansError && (
                        <Alert status="error" rounded="xl">
                          <AlertIcon />
                          {t("userDialog.planLoadError")}
                        </Alert>
                      )}
                    </VStack>
                  ) : (
              <Grid
                templateColumns={{
                  base: "repeat(1, 1fr)",
                  md: "repeat(2, 1fr)",
                }}
                gap={3}
              >
                <GridItem>
                  <VStack justifyContent="space-between">
                    <Flex
                      flexDirection="column"
                      gridAutoRows="min-content"
                      w="full"
                    >
                      <Flex flexDirection="row" w="full" gap={2}>
                        <FormControl mb={"10px"}>
                          <FormLabel>
                            <Flex gap={2} alignItems={"center"}>
                              {t("username")}
                              {!isEditing && (
                                <ReloadIcon
                                  cursor={"pointer"}
                                  className={classNames({
                                    "animate-spin": randomUsernameLoading,
                                  })}
                                  onClick={() => {
                                    const randomUsername =
                                      createRandomUsername();
                                    form.setValue("username", randomUsername);
                                    setTimeout(() => {
                                      setrandomUsernameLoading(false);
                                    }, 350);
                                  }}
                                />
                              )}
                            </Flex>
                          </FormLabel>
                          <Input
                            size="sm"
                            type="text"
                            borderRadius="6px"
                            error={form.formState.errors.username?.message}
                            disabled={disabled || isEditing}
                            {...form.register("username")}
                          />
                        </FormControl>
                        {!isEditing && (
                          <FormControl flex="1">
                            <FormLabel whiteSpace={"nowrap"}>
                              {t("userDialog.onHold")}
                            </FormLabel>
                            <Controller
                              name="status"
                              control={form.control}
                              render={({ field }) => {
                                const status = field.value;
                                return (
                                  <>
                                    {status ? (
                                      <Switch
                                        colorScheme="primary"
                                        isChecked={status === "on_hold"}
                                        onChange={(e) => {
                                          if (e.target.checked) {
                                            field.onChange("on_hold");
                                          } else {
                                            field.onChange("active");
                                          }
                                        }}
                                      />
                                    ) : (
                                      ""
                                    )}
                                  </>
                                );
                              }}
                            />
                          </FormControl>
                        )}
                      </Flex>
                      <FormControl mb={"10px"}>
                        <FormLabel>{t("userDialog.dataLimit")}</FormLabel>
                        <Controller
                          control={form.control}
                          name="data_limit"
                          render={({ field }) => {
                            return (
                              <Input
                                endAdornment="GB"
                                type="number"
                                size="sm"
                                borderRadius="6px"
                                onChange={field.onChange}
                                disabled={disabled}
                                error={
                                  form.formState.errors.data_limit?.message
                                }
                                value={field.value ? String(field.value) : ""}
                              />
                            );
                          }}
                        />
                      </FormControl>
                      <Collapse
                        in={!!(dataLimit && dataLimit > 0)}
                        animateOpacity
                        style={{ width: "100%" }}
                      >
                        <FormControl height="66px">
                          <FormLabel>
                            {t("userDialog.periodicUsageReset")}
                          </FormLabel>
                          <Controller
                            control={form.control}
                            name="data_limit_reset_strategy"
                            render={({ field }) => {
                              return (
                                <Select
                                  size="sm"
                                  {...field}
                                  disabled={disabled}
                                  bg={disabled ? "gray.100" : "transparent"}
                                  _dark={{
                                    bg: disabled ? "gray.600" : "transparent",
                                  }}
                                  sx={{
                                    option: {
                                      backgroundColor:
                                        colorMode === "dark"
                                          ? "#222C3B"
                                          : "white",
                                    },
                                  }}
                                >
                                  {resetStrategy.map((s) => {
                                    return (
                                      <option key={s.value} value={s.value}>
                                        {t(
                                          "userDialog.resetStrategy" + s.title
                                        )}
                                      </option>
                                    );
                                  })}
                                </Select>
                              );
                            }}
                          />
                        </FormControl>
                      </Collapse>

                      <FormControl mb={"10px"}>
                        <FormLabel>
                          {isOnHold
                            ? t("userDialog.onHoldExpireDuration")
                            : t("userDialog.expiryDate")}
                        </FormLabel>

                        {isOnHold && (
                          <Controller
                            control={form.control}
                            name="on_hold_expire_duration"
                            render={({ field }) => {
                              return (
                                <Input
                                  endAdornment="Days"
                                  type="number"
                                  size="sm"
                                  borderRadius="6px"
                                  onChange={(on_hold) => {
                                    form.setValue("expire", null);
                                    field.onChange({
                                      target: {
                                        value: on_hold,
                                      },
                                    });
                                  }}
                                  disabled={disabled}
                                  error={
                                    form.formState.errors
                                      .on_hold_expire_duration?.message
                                  }
                                  value={field.value ? String(field.value) : ""}
                                />
                              );
                            }}
                          />
                        )}
                        {!isOnHold && (
                          <Controller
                            name="expire"
                            control={form.control}
                            render={({ field }) => {
                              function createDateAsUTC(num: number) {
                                return dayjs(
                                  dayjs(num * 1000).utc()
                                  // .format("MMMM D, YYYY") // exception with: dayjs.locale(lng);
                                ).toDate();
                              }
                              const { status, time } = relativeExpiryDate(
                                field.value
                              );
                              return (
                                <>
                                  <ReactDatePicker
                                    popperClassName="user-expiry-datepicker-popper"
                                    popperPlacement="top-start"
                                    popperModifiers={[
                                      {
                                        name: "offset",
                                        options: { offset: [0, 10] },
                                      },
                                      {
                                        name: "preventOverflow",
                                        options: {
                                          rootBoundary: "viewport",
                                          altAxis: true,
                                          padding: 12,
                                        },
                                      },
                                      {
                                        name: "flip",
                                        options: {
                                          fallbackPlacements: [
                                            "bottom-start",
                                            "top-end",
                                          ],
                                        },
                                      },
                                    ]}
                                    locale={i18n.language.toLocaleLowerCase()}
                                    dateFormat={t("dateFormat")}
                                    minDate={new Date()}
                                    selected={
                                      field.value
                                        ? createDateAsUTC(field.value)
                                        : undefined
                                    }
                                    onChange={(date: Date) => {
                                      form.setValue(
                                        "on_hold_expire_duration",
                                        null
                                      );
                                      field.onChange({
                                        target: {
                                          value: date
                                            ? dayjs(
                                                dayjs(date)
                                                  .set("hour", 23)
                                                  .set("minute", 59)
                                                  .set("second", 59)
                                              )
                                                .utc()
                                                .valueOf() / 1000
                                            : 0,
                                          name: "expire",
                                        },
                                      });
                                    }}
                                    customInput={
                                      <Input
                                        size="sm"
                                        type="text"
                                        borderRadius="6px"
                                        clearable
                                        disabled={disabled}
                                        error={
                                          form.formState.errors.expire?.message
                                        }
                                      />
                                    }
                                  />
                                  {field.value ? (
                                    <FormHelperText>
                                      {t(status, { time: time })}
                                    </FormHelperText>
                                  ) : (
                                    ""
                                  )}
                                </>
                              );
                            }}
                          />
                        )}
                      </FormControl>

                      <FormControl
                        mb={"10px"}
                        isInvalid={!!form.formState.errors.note}
                      >
                        <FormLabel>{t("userDialog.note")}</FormLabel>
                        <Textarea {...form.register("note")} />
                        <FormErrorMessage>
                          {form.formState.errors?.note?.message}
                        </FormErrorMessage>
                      </FormControl>
                    </Flex>
                    {error && (
                      <Alert
                        status="error"
                        display={{ base: "none", md: "flex" }}
                      >
                        <AlertIcon />
                        {error}
                      </Alert>
                    )}
                  </VStack>
                </GridItem>
                <GridItem>
                  <FormLabel>{t("userDialog.nodeEntitlement")}</FormLabel>
                  {entitlementLoading && (
                    <Flex
                      minH="280px"
                      align="center"
                      justify="center"
                      layerStyle="glassSubtle"
                      rounded="2xl"
                    >
                      <Spinner color="primary.500" />
                    </Flex>
                  )}
                  {entitlementError && (
                    <Alert status="error" alignItems="flex-start" rounded="2xl">
                      <AlertIcon mt="0.5" />
                      <Box>
                        <Text fontWeight="700">
                          {t("userDialog.entitlementLoadError")}
                        </Text>
                        <Text mt="1" fontSize="sm">
                          {t("userDialog.entitlementLoadErrorHelp")}
                        </Text>
                      </Box>
                    </Alert>
                  )}
                  {!entitlementLoading &&
                    !entitlementError &&
                    entitlement?.managed_by_plan && (
                      <VStack
                        align="stretch"
                        spacing="4"
                        layerStyle="glassSubtle"
                        rounded="2xl"
                        p="4"
                      >
                        <Flex
                          justify="space-between"
                          align="flex-start"
                          gap="3"
                        >
                          <Box minW="0">
                            <HStack spacing="2" flexWrap="wrap">
                              <Text
                                fontSize="lg"
                                fontWeight="800"
                                noOfLines={1}
                              >
                                {entitlement.plan_name || "—"}
                              </Text>
                              <Badge
                                colorScheme={
                                  userStatus === "disabled"
                                    ? "red"
                                    : entitlement.disabled_at
                                    ? "gray"
                                    : "green"
                                }
                                rounded="full"
                              >
                                {t(
                                  userStatus === "disabled"
                                    ? "userDialog.userBlocked"
                                    : entitlement.disabled_at
                                    ? "userDialog.planDisabled"
                                    : "userDialog.planManaged"
                                )}
                              </Badge>
                            </HStack>
                            <Text mt="1" fontSize="sm" color="fg.muted">
                              {t("userDialog.planManagedHelp")}
                            </Text>
                          </Box>
                        </Flex>

                        <Box>
                          <Text fontSize="xs" fontWeight="700" color="fg.muted">
                            {t("userDialog.localNodes")}
                          </Text>
                          <HStack mt="2" spacing="2" flexWrap="wrap">
                            {entitlement.inbound_tags.length ? (
                              entitlement.inbound_tags.map((tag) => (
                                <Badge key={tag} px="2.5" py="1" rounded="full">
                                  {tag}
                                </Badge>
                              ))
                            ) : (
                              <Text fontSize="sm" color="fg.subtle">
                                {t("userDialog.noLocalNodes")}
                              </Text>
                            )}
                          </HStack>
                        </Box>

                        <Box>
                          <Text fontSize="xs" fontWeight="700" color="fg.muted">
                            {t("userDialog.externalSources")}
                          </Text>
                          <VStack mt="2" align="stretch" spacing="2">
                            {entitlement.external_sources.length ? (
                              entitlement.external_sources.map((source) => (
                                <Flex
                                  key={source.source_id}
                                  justify="space-between"
                                  gap="3"
                                  rounded="xl"
                                  borderWidth="1px"
                                  borderColor="border.subtle"
                                  px="3"
                                  py="2.5"
                                >
                                  <Box minW="0">
                                    <Text fontWeight="700" noOfLines={1}>
                                      {source.name}
                                    </Text>
                                    <Text
                                      fontSize="xs"
                                      color="fg.subtle"
                                      noOfLines={1}
                                    >
                                      {source.group_name}
                                    </Text>
                                  </Box>
                                  <Badge alignSelf="center" rounded="full">
                                    {source.mode === "all"
                                      ? t("userDialog.allExternalNodes", {
                                          count: source.node_count,
                                        })
                                      : t("userDialog.selectedExternalNodes", {
                                          count: source.node_count,
                                        })}
                                  </Badge>
                                </Flex>
                              ))
                            ) : (
                              <Text fontSize="sm" color="fg.subtle">
                                {t("userDialog.noExternalSources")}
                              </Text>
                            )}
                          </VStack>
                        </Box>

                        {entitlement.expires_at && (
                          <Text fontSize="sm" color="fg.muted">
                            {t("userDialog.planExpiresAt", {
                              date: dayjs(entitlement.expires_at).format(
                                "YYYY-MM-DD"
                              ),
                            })}
                          </Text>
                        )}
                        {adminUser.is_sudo && (
                          <HStack align="stretch" flexWrap="wrap">
                            <Button
                              type="button"
                              colorScheme="primary"
                              variant="outline"
                              onClick={openPlanManagement}
                            >
                              {t("userDialog.managePlan")}
                            </Button>
                            <Button
                              type="button"
                              variant="outline"
                              onClick={handleResetPassword}
                              isLoading={loading}
                            >
                              {t("userDialog.resetLoginPassword")}
                            </Button>
                          </HStack>
                        )}
                      </VStack>
                    )}
                  {!entitlementLoading &&
                    !entitlementError &&
                    !entitlement?.managed_by_plan && (
                      <FormControl
                        isInvalid={
                          !!form.formState.errors.selected_proxies?.message
                        }
                      >
                        <Text mb="3" fontSize="sm" color="fg.muted">
                          {t("userDialog.manualEntitlementHelp")}
                        </Text>
                        <Controller
                          control={form.control}
                          name="selected_proxies"
                          render={({ field }) => {
                            return (
                              <RadioGroup
                                list={[
                                  {
                                    title: "vmess",
                                    description: t("userDialog.vmessDesc"),
                                  },
                                  {
                                    title: "vless",
                                    description: t("userDialog.vlessDesc"),
                                  },
                                  {
                                    title: "trojan",
                                    description: t("userDialog.trojanDesc"),
                                  },
                                  {
                                    title: "shadowsocks",
                                    description: t(
                                      "userDialog.shadowsocksDesc"
                                    ),
                                  },
                                ]}
                                disabled={disabled}
                                {...field}
                              />
                            );
                          }}
                        />
                        <FormErrorMessage>
                          {t(
                            form.formState.errors.selected_proxies
                              ?.message as string
                          )}
                        </FormErrorMessage>
                      </FormControl>
                    )}
                </GridItem>
                {isEditing && usageVisible && (
                  <GridItem pt={6} colSpan={{ base: 1, md: 2 }}>
                    <VStack gap={4}>
                      <UsageFilter
                        defaultValue={usageFilter}
                        onChange={(filter, query) => {
                          setUsageFilter(filter);
                          fetchUsageWithFilter(query);
                        }}
                      />
                      <Box
                        width={{ base: "100%", md: "70%" }}
                        justifySelf="center"
                      >
                        <ReactApexChart
                          options={usage.options}
                          series={usage.series}
                          type="donut"
                        />
                      </Box>
                    </VStack>
                  </GridItem>
                )}
              </Grid>
                  )}
              {error && (
                <Alert
                  mt="3"
                  status="error"
                  display="flex"
                >
                  <AlertIcon />
                  {error}
                </Alert>
              )}
                </>
              )}
            </ModalBody>
            <ModalFooter mt="3">
              {generatedPassword ? (
                <Button colorScheme="primary" onClick={onClose}>
                  {t("close")}
                </Button>
              ) : (
              <HStack
                justifyContent="space-between"
                w="full"
                gap={3}
                flexDirection={{
                  base: "column",
                  sm: "row",
                }}
              >
                <HStack
                  justifyContent="flex-start"
                  w={{
                    base: "full",
                    sm: "unset",
                  }}
                >
                  {isEditing && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        colorScheme="red"
                        leftIcon={<DeleteIcon />}
                        onClick={() => {
                          onDeletingUser(editingUser);
                          onClose();
                        }}
                      >
                        {t("userDialog.deleteUser")}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        colorScheme={userStatus === "active" ? "orange" : "green"}
                        leftIcon={
                          userStatus === "active" ? (
                            <NoSymbolIcon width="16" />
                          ) : (
                            <CheckCircleIcon width="16" />
                          )
                        }
                        onClick={handleStatusAction}
                        isLoading={loading}
                        isDisabled={entitlementLoading || entitlementError}
                      >
                        {t(
                          userStatus === "active"
                            ? "userDialog.disableUser"
                            : "userDialog.enableUser"
                        )}
                      </Button>
                      <Tooltip label={t("userDialog.usage")} placement="top">
                        <IconButton
                          aria-label="usage"
                          size="sm"
                          onClick={handleUsageToggle}
                        >
                          <UserUsageIcon />
                        </IconButton>
                      </Tooltip>
                      <Button onClick={handleResetUsage} size="sm">
                        {t("userDialog.resetUsage")}
                      </Button>
                      <Button onClick={handleRevokeSubscription} size="sm">
                        {t("userDialog.revokeSubscription")}
                      </Button>
                    </>
                  )}
                </HStack>
                <HStack
                  w="full"
                  maxW={{ md: "50%", base: "full" }}
                  justify="end"
                >
                  <Button
                    type="submit"
                    size="sm"
                    px="8"
                    colorScheme="primary"
                    leftIcon={loading ? <Spinner size="xs" /> : undefined}
                    disabled={
                      submitDisabled ||
                      (!isEditing &&
                        creationMode === "managed" &&
                        (!planId || plansLoading || plansError))
                    }
                  >
                    {isEditing ? t("userDialog.editUser") : t("createUser")}
                  </Button>
                </HStack>
              </HStack>
              )}
            </ModalFooter>
          </form>
        </ModalContent>
      </FormProvider>
    </Modal>
  );
};
