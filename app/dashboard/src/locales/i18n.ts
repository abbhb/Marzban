import { joinPaths } from "@remix-run/router";

import dayjs from "dayjs";
import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import HttpApi from "i18next-http-backend";
import { initReactI18next } from "react-i18next";
import { version as dashboardVersion } from "../../package.json";

const syncDocumentLanguage = (lng: string) => {
    document.documentElement.lang = lng;
    document.documentElement.dir = i18n.dir(lng);
};

declare module "i18next" {
    interface CustomTypeOptions {
        returnNull: false;
    }
}

export const i18nReady = new Promise<void>((resolve, reject) => {
    i18n
        .use(LanguageDetector)
        .use(initReactI18next)
        .use(HttpApi)
        .init(
        {
            debug: import.meta.env.NODE_ENV === "development",
            returnNull: false,
            fallbackLng: "en",
            interpolation: {
                escapeValue: false,
            },
            react: {
                useSuspense: false,
            },
            load: "languageOnly",
            detection: {
                caches: ["localStorage", "sessionStorage", "cookie"],
            },
            backend: {
                loadPath: joinPaths([
                    import.meta.env.BASE_URL,
                    `statics/locales/{{lng}}.json`,
                ]),
                // The versioned URL makes the stable public filename safe to
                // cache while still replacing it on every dashboard release.
                queryStringParams: {
                    v: dashboardVersion,
                },
            },
        },
        function (err) {
            dayjs.locale(i18n.language);
            syncDocumentLanguage(i18n.language);
            if (err) reject(err);
            else resolve();
        }
    );
});

i18n.on("languageChanged", (lng) => {
    dayjs.locale(lng);
    syncDocumentLanguage(lng);
});

export default i18n;
