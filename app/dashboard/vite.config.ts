import react from "@vitejs/plugin-react";
import { gzipSync } from "zlib";
import { defineConfig, Plugin, splitVendorChunkPlugin } from "vite";
import svgr from "vite-plugin-svgr";
import { visualizer } from "rollup-plugin-visualizer";
import tsconfigPaths from "vite-tsconfig-paths";

const INITIAL_GZIP_BUDGET = 350 * 1024;
const INITIAL_JS_GZIP_BUDGET = 260 * 1024;
const INITIAL_CSS_GZIP_BUDGET = 50 * 1024;
const INITIAL_REQUEST_BUDGET = 12;
const INDEX_HTML_RAW_BUDGET = 10 * 1024;
const ROUTE_RAW_BUDGET = 1024 * 1024;
const ROUTE_GZIP_BUDGET = 320 * 1024;
const ROUTE_REQUEST_BUDGET = 18;

// Public locales are copied after Rollup's generateBundle hook, so route
// profiles reserve conservative fixed space for the largest locale and HTML.
// transformIndexHtml below enforces the real HTML raw-size ceiling separately.
const ROUTE_HTML_RAW_OVERHEAD = INDEX_HTML_RAW_BUDGET;
const ROUTE_HTML_GZIP_OVERHEAD = 4 * 1024;
const ROUTE_LOCALE_RAW_OVERHEAD = 40 * 1024;
const ROUTE_LOCALE_GZIP_OVERHEAD = 12 * 1024;
const ROUTE_FIXED_REQUEST_OVERHEAD = 2;

const ROUTE_PROFILES = {
  admin: ["/src/pages/Dashboard.tsx"],
  login: ["/src/pages/Login.tsx"],
  "portal-overview": [
    "/src/pages/portal/PortalLayout.tsx",
    "/src/pages/portal/PortalOverview.tsx",
  ],
  "commerce-default": [
    "/src/pages/CommerceAdmin.tsx",
    "/src/pages/commerce/PlansWorkspace.tsx",
  ],
} as const;

const FORBIDDEN_INITIAL_MODULES = [
  { name: "jsoneditor", pattern: /\/node_modules\/jsoneditor\// },
  {
    name: "apexcharts",
    pattern: /\/node_modules\/(?:react-)?apexcharts\//,
  },
  {
    name: "react-datepicker",
    pattern: /\/node_modules\/react-datepicker\//,
  },
  { name: "qrcode.react", pattern: /\/node_modules\/qrcode\.react\// },
  { name: "react-slick", pattern: /\/node_modules\/react-slick\// },
] as const;

const initialBundleBudget = (): Plugin => ({
  name: "marzban-initial-bundle-budget",
  transformIndexHtml: {
    enforce: "post",
    transform(html) {
      const raw = Buffer.byteLength(html);
      if (raw > INDEX_HTML_RAW_BUDGET) {
        throw new Error(
          `index.html is ${raw} bytes; ` +
            `the inline-shell budget is ${INDEX_HTML_RAW_BUDGET} bytes.`
        );
      }
      return html;
    },
  },
  generateBundle(_, bundle) {
    const entries = Object.values(bundle).filter(
      (item) => item.type === "chunk" && item.isEntry
    );
    const collectResources = (rootFileNames: string[]) => {
      const chunks = new Set<string>();
      const css = new Set<string>();

      const visit = (fileName: string) => {
        if (chunks.has(fileName)) return;
        const item = bundle[fileName];
        if (!item || item.type !== "chunk") return;
        chunks.add(fileName);
        item.imports.forEach(visit);
        const metadata = (
          item as typeof item & {
            viteMetadata?: { importedCss?: Set<string> };
          }
        ).viteMetadata;
        metadata?.importedCss?.forEach((file) => css.add(file));
      };

      rootFileNames.forEach(visit);
      return {
        chunks,
        resources: [
          ...Array.from(chunks, (fileName) => ({
            fileName,
            kind: "js" as const,
            source: bundle[fileName].type === "chunk"
              ? bundle[fileName].code
              : "",
          })),
          ...Array.from(css, (fileName) => {
            const asset = bundle[fileName];
            return {
              fileName,
              kind: "css" as const,
              source: asset?.type === "asset" ? asset.source : "",
            };
          }),
        ],
      };
    };

    const measure = (
      resources: ReturnType<typeof collectResources>["resources"]
    ) => resources.map(({ fileName, kind, source }) => ({
      fileName,
      kind,
      raw: Buffer.byteLength(source),
      gzip: gzipSync(source).byteLength,
    }));

    const initial = collectResources(entries.map((entry) => entry.fileName));
    const resources = initial.resources;
    const measured = measure(resources);
    const totalGzip = measured.reduce((total, item) => total + item.gzip, 0);

    for (const item of measured) {
      const limit =
        item.kind === "js" ? INITIAL_JS_GZIP_BUDGET : INITIAL_CSS_GZIP_BUDGET;
      if (item.gzip > limit) {
        this.error(
          `${item.fileName} is ${(item.gzip / 1024).toFixed(1)} KiB gzip; ` +
            `the initial ${item.kind.toUpperCase()} limit is ${limit / 1024} KiB.`
        );
      }
    }
    if (totalGzip > INITIAL_GZIP_BUDGET) {
      this.error(
        `Initial resources are ${(totalGzip / 1024).toFixed(1)} KiB gzip; ` +
          `the budget is ${INITIAL_GZIP_BUDGET / 1024} KiB.`
      );
    }
    if (resources.length > INITIAL_REQUEST_BUDGET) {
      this.error(
        `Initial resources need ${resources.length} requests; ` +
          `the budget is ${INITIAL_REQUEST_BUDGET}.`
      );
    }

    console.log(
      `Initial bundle: ${(totalGzip / 1024).toFixed(1)} KiB gzip in ` +
        `${resources.length} requests (budget ${INITIAL_GZIP_BUDGET / 1024} KiB).`
    );
    console.log(
      "Route profiles reserve 10/4 KiB raw/gzip for HTML and " +
        "40/12 KiB for one locale (2 requests)."
    );

    const entryFiles = entries.map((entry) => entry.fileName);
    for (const [profileName, moduleSuffixes] of Object.entries(
      ROUTE_PROFILES
    )) {
      const routeFiles = moduleSuffixes.map((moduleSuffix) => {
        const routeChunk = Object.values(bundle).find(
          (item) => {
            if (item.type !== "chunk") return false;
            const facadeMatches = item.facadeModuleId
              ?.replace(/\\/g, "/")
              .endsWith(moduleSuffix);
            const moduleMatches = Object.keys(item.modules).some((moduleId) =>
              moduleId.replace(/\\/g, "/").endsWith(moduleSuffix)
            );
            return facadeMatches || moduleMatches;
          }
        );
        if (!routeChunk || routeChunk.type !== "chunk") {
          this.error(
            `Route profile ${profileName} cannot find ${moduleSuffix}.`
          );
        }
        return routeChunk.fileName;
      });
      const route = collectResources([...entryFiles, ...routeFiles]);
      const routeMeasured = measure(route.resources);
      const raw =
        routeMeasured.reduce((total, item) => total + item.raw, 0) +
        ROUTE_HTML_RAW_OVERHEAD +
        ROUTE_LOCALE_RAW_OVERHEAD;
      const gzip =
        routeMeasured.reduce((total, item) => total + item.gzip, 0) +
        ROUTE_HTML_GZIP_OVERHEAD +
        ROUTE_LOCALE_GZIP_OVERHEAD;
      const requests =
        route.resources.length + ROUTE_FIXED_REQUEST_OVERHEAD;

      const reachableModules = Array.from(route.chunks).flatMap((fileName) => {
        const chunk = bundle[fileName];
        return chunk?.type === "chunk"
          ? Object.keys(chunk.modules).map((moduleId) =>
              moduleId.replace(/\\/g, "/")
            )
          : [];
      });
      for (const forbidden of FORBIDDEN_INITIAL_MODULES) {
        const offender = reachableModules.find((moduleId) =>
          forbidden.pattern.test(moduleId)
        );
        if (offender) {
          this.error(
            `Route profile ${profileName} reaches forbidden initial module ` +
              `${forbidden.name}: ${offender}.`
          );
        }
      }

      if (raw > ROUTE_RAW_BUDGET) {
        this.error(
          `Route profile ${profileName} is ${(raw / 1024).toFixed(1)} KiB raw; ` +
            `the budget is ${ROUTE_RAW_BUDGET / 1024} KiB.`
        );
      }
      if (gzip > ROUTE_GZIP_BUDGET) {
        this.error(
          `Route profile ${profileName} is ${(gzip / 1024).toFixed(1)} KiB gzip; ` +
            `the budget is ${ROUTE_GZIP_BUDGET / 1024} KiB.`
        );
      }
      if (requests > ROUTE_REQUEST_BUDGET) {
        this.error(
          `Route profile ${profileName} needs ${requests} static requests; ` +
            `the budget is ${ROUTE_REQUEST_BUDGET}.`
        );
      }

      console.log(
        `Route ${profileName}: ${(raw / 1024).toFixed(1)} KiB raw / ` +
          `${(gzip / 1024).toFixed(1)} KiB gzip in ${requests} static requests.`
      );
    }
  },
});

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    tsconfigPaths(),
    react({
      include: "**/*.tsx",
    }),
    svgr(),
    ...(process.env.ANALYZE ? [visualizer()] : []),
    splitVendorChunkPlugin(),
    initialBundleBudget(),
  ],
});
