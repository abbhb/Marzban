import {
  Button,
  chakra,
  Input,
  InputGroup,
  InputRightElement,
  Tooltip,
  useToast,
} from "@chakra-ui/react";
import { CheckIcon, ClipboardIcon } from "@heroicons/react/24/outline";
import copyToClipboard from "copy-to-clipboard";
import { FC, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const CopyIcon = chakra(ClipboardIcon, { baseStyle: { w: 4, h: 4 } });
const CopiedIcon = chakra(CheckIcon, { baseStyle: { w: 4, h: 4 } });

type SubscriptionLinkFieldProps = {
  value: string;
};

export const SubscriptionLinkField: FC<SubscriptionLinkFieldProps> = ({
  value,
}) => {
  const { t } = useTranslation();
  const toast = useToast();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setCopied(false);
  }, [value]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = useCallback(async () => {
    let succeeded = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        succeeded = true;
      }
    } catch {
      // Browser policy can deny the async API. The synchronous fallback still
      // works in older WebViews and when clipboard permission is unavailable.
    }

    if (!succeeded) {
      try {
        succeeded = copyToClipboard(value, { format: "text/plain" });
      } catch {
        succeeded = false;
      }
    }

    if (succeeded) {
      setCopied(true);
      return;
    }

    toast({
      title: t("mgma.copyFailed"),
      status: "error",
      isClosable: true,
      position: "top",
      duration: 3000,
    });
  }, [t, toast, value]);

  return (
    <InputGroup>
      <Input
        value={value}
        readOnly
        fontFamily="mono"
        fontSize="xs"
        pr="2.75rem"
        autoComplete="off"
        spellCheck={false}
        bg="surface.input"
        onFocus={(event) => event.currentTarget.select()}
      />
      <InputRightElement>
        <Tooltip label={t(copied ? "usersTable.copied" : "mgma.copy")}>
          <Button
            type="button"
            aria-label={String(t(copied ? "usersTable.copied" : "mgma.copy"))}
            variant="ghost"
            size="sm"
            minW="auto"
            px={2}
            colorScheme={copied ? "green" : "gray"}
            onClick={() => void copy()}
          >
            {copied ? <CopiedIcon /> : <CopyIcon />}
          </Button>
        </Tooltip>
      </InputRightElement>
    </InputGroup>
  );
};
