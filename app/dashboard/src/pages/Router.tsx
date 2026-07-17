import {
    ComponentType,
    LazyExoticComponent,
    Suspense,
    lazy,
} from "react";
import {
    LoaderFunctionArgs,
    createHashRouter,
    redirect,
} from "react-router-dom";
import { BootReady } from "../components/BootReady";
import { ChunkLoadBoundary } from "../components/ChunkLoadBoundary";
import { StatisticsQueryKey } from "../constants/QueryKeys";
import { fetch, portalFetch } from "../service/http";
import { getAuthToken } from "../utils/authStorage";
import { removeAuthToken } from "../utils/authStorage";
import { queryClient } from "../utils/react-query";
import { getPortalAuthToken } from "../utils/portalAuthStorage";
import { removePortalAuthToken } from "../utils/portalAuthStorage";

const Dashboard = lazy(() =>
    import("./Dashboard").then(({ Dashboard }) => ({ default: Dashboard }))
);
const AdminError = lazy(() =>
    import("./AdminError").then(({ AdminError }) => ({ default: AdminError }))
);
const Login = lazy(() =>
    import("./Login").then(({ Login }) => ({ default: Login }))
);
const CommerceAdmin = lazy(() =>
    import("./CommerceAdmin").then(({ CommerceAdmin }) => ({
        default: CommerceAdmin,
    }))
);
const PortalLogin = lazy(() =>
    import("./PortalLogin").then(({ PortalLogin }) => ({ default: PortalLogin }))
);
const PortalRegister = lazy(() =>
    import("./PortalRegister").then(({ PortalRegister }) => ({
        default: PortalRegister,
    }))
);
const PortalAccess = lazy(() =>
    import("./portal/PortalAccess").then(({ PortalAccess }) => ({
        default: PortalAccess,
    }))
);
const PortalError = lazy(() =>
    import("./portal/PortalError").then(({ PortalError }) => ({
        default: PortalError,
    }))
);
const PortalLayout = lazy(() =>
    import("./portal/PortalLayout").then(({ PortalLayout }) => ({
        default: PortalLayout,
    }))
);
const PortalOverview = lazy(() =>
    import("./portal/PortalOverview").then(({ PortalOverview }) => ({
        default: PortalOverview,
    }))
);
const PortalPlans = lazy(() =>
    import("./portal/PortalPlans").then(({ PortalPlans }) => ({
        default: PortalPlans,
    }))
);
const PortalWallet = lazy(() =>
    import("./portal/PortalWallet").then(({ PortalWallet }) => ({
        default: PortalWallet,
    }))
);

export const preloadInitialRoute = async () => {
    const path =
        window.location.hash
            .replace(/^#/, "")
            .split("?")[0]
            .replace(/\/+$/, "") || "/";

    if (path === "/login") return import("./PortalLogin");
    if (path === "/login/admin" || path === "/admin") {
        return import("./Login");
    }
    if (path === "/portal/login") return import("./PortalLogin");
    if (path === "/portal/register") return import("./PortalRegister");

    if (path.startsWith("/portal")) {
        if (!getPortalAuthToken()) return import("./PortalLogin");
        const leaf =
            path === "/portal/plans"
                ? import("./portal/PortalPlans")
                : path === "/portal/access"
                ? import("./portal/PortalAccess")
                : path === "/portal/wallet"
                ? import("./portal/PortalWallet")
                : import("./portal/PortalOverview");
        return Promise.all([import("./portal/PortalLayout"), leaf]);
    }

    if (path === "/commerce") {
        if (!getAuthToken()) return import("./Login");
        return Promise.all([
            import("./CommerceAdmin"),
            import("./commerce/PlansWorkspace"),
        ]);
    }
    if (!getAuthToken()) {
        if (path === "/" && getPortalAuthToken()) {
            return Promise.all([
                import("./portal/PortalLayout"),
                import("./portal/PortalOverview"),
            ]);
        }
        return import("./PortalLogin");
    }
    return Promise.all([
        import("./Dashboard"),
        import("../contexts/DashboardContext"),
    ]);
};

const routeElement = (
    Page: LazyExoticComponent<ComponentType>,
    completesBoot = true
) => (
    <ChunkLoadBoundary>
        <Suspense fallback={null}>
            <Page />
            {completesBoot ? <BootReady /> : null}
        </Suspense>
    </ChunkLoadBoundary>
);

const fetchAdminLoader = async ({ request }: LoaderFunctionArgs) => {
    try {
        return await fetch("/admin", {
            timeout: 15000,
            signal: request.signal,
            headers: {
                Authorization: `Bearer ${getAuthToken()}`,
            },
        });
    } catch (error: any) {
        const status = error?.statusCode || error?.response?.status;
        if (status === 401 || status === 403) {
            removeAuthToken();
            throw redirect("/login/admin");
        }
        throw error;
    }
};

const fetchDashboardLoader = async (args: LoaderFunctionArgs) => {
    if (!getAuthToken()) {
        if (getPortalAuthToken()) {
            throw redirect("/portal");
        }
        throw redirect("/login");
    }

    const admin = await fetchAdminLoader(args);
    const [{ fetchUsers, useDashboard }] = await Promise.all([
        import("../contexts/DashboardContext"),
        import("./Dashboard"),
    ]);

    const [usersResult] = await Promise.allSettled([
        fetchUsers(useDashboard.getState().filters, args.request.signal),
        queryClient.prefetchQuery(
            StatisticsQueryKey,
            () =>
                fetch("/system", {
                    timeout: 15000,
                    signal: args.request.signal,
                }),
            { staleTime: 30000 }
        ),
    ]);
    if (usersResult.status === "rejected") throw usersResult.reason;
    return admin;
};

const fetchPortalLoader = async ({ request }: LoaderFunctionArgs) => {
    try {
        return await portalFetch("/portal/me", {
            timeout: 15000,
            signal: request.signal,
        });
    } catch (error: any) {
        const status = error?.statusCode || error?.response?.status;
        if (status === 401) {
            removePortalAuthToken();
            return redirect("/login");
        }
        throw error;
    }
};
export const router = createHashRouter([
    {
        path: "/",
        element: routeElement(Dashboard),
        errorElement: routeElement(AdminError),
        loader: fetchDashboardLoader,
    },
    {
        path: "/commerce/",
        element: routeElement(CommerceAdmin, false),
        errorElement: routeElement(AdminError),
        loader: fetchAdminLoader,
    },
    {
        path: "/login/",
        element: routeElement(PortalLogin),
    },
    {
        path: "/login/admin/",
        element: routeElement(Login),
    },
    {
        path: "/admin/",
        loader: () => redirect("/login/admin"),
    },
    {
        path: "/portal/",
        element: routeElement(PortalLayout, false),
        errorElement: routeElement(PortalError),
        loader: fetchPortalLoader,
        children: [
            { index: true, element: routeElement(PortalOverview) },
            { path: "plans", element: routeElement(PortalPlans, false) },
            { path: "access", element: routeElement(PortalAccess) },
            { path: "wallet", element: routeElement(PortalWallet, false) },
        ],
    },
    {
        path: "/portal/login/",
        loader: () => redirect("/login"),
    },
    {
        path: "/portal/register/",
        element: routeElement(PortalRegister),
    },
]);
