import {
  chakra,
  IconButton,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
} from "@chakra-ui/react";
import { LanguageIcon } from "@heroicons/react/24/outline";
import { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";

type HeaderProps = {
  actions?: ReactNode;
};

const LangIcon = chakra(LanguageIcon, {
  baseStyle: {
    w: 4,
    h: 4,
  },
});

export const Language: FC<HeaderProps> = ({ actions }) => {
  const { i18n, t } = useTranslation();

  var changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
  };

  return (
    <Menu placement="bottom-end">
      <MenuButton
        as={IconButton}
        size="sm"
        variant="ghost"
        icon={<LangIcon />}
        position="relative"
        w="9"
        h="9"
        minW="9"
        aria-label={t("language")}
      />
      <Portal>
        <MenuList minW="128px" zIndex="popover">
          <MenuItem fontSize="sm" onClick={() => changeLanguage("en")}>
            English
          </MenuItem>
          <MenuItem fontSize="sm" onClick={() => changeLanguage("fa")}>
            فارسی
          </MenuItem>
          <MenuItem fontSize="sm" onClick={() => changeLanguage("zh-cn")}>
            简体中文
          </MenuItem>
          <MenuItem fontSize="sm" onClick={() => changeLanguage("ru")}>
            Русский
          </MenuItem>
        </MenuList>
      </Portal>
    </Menu>
  );
};
