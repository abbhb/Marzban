import { createHashRouter, redirect } from "react-router-dom";
import { fetch, portalFetch } from "../service/http";
import { getAuthToken } from "../utils/authStorage";
import { Dashboard } from "./Dashboard";
import { Login } from "./Login";
import { CommerceAdmin } from "./CommerceAdmin";
import { PortalLogin } from "./PortalLogin";
import { PortalRegister } from "./PortalRegister";
import { PortalAccess } from "./portal/PortalAccess";
import { PortalError } from "./portal/PortalError";
import { PortalLayout } from "./portal/PortalLayout";
import { PortalOverview } from "./portal/PortalOverview";
import { PortalPlans } from "./portal/PortalPlans";
import { PortalWallet } from "./portal/PortalWallet";
import { removePortalAuthToken } from "utils/portalAuthStorage";
const fetchAdminLoader = () => {
    return fetch("/admin", {
        headers: {
            Authorization: `Bearer ${getAuthToken()}`,
        },
    });
};
const fetchPortalLoader = async () => {
    try {
        return await portalFetch("/portal/me");
    } catch (error: any) {
        const status = error?.statusCode || error?.response?.status;
        if (status === 401) {
            removePortalAuthToken();
            return redirect("/portal/login");
        }
        throw error;
    }
};
export const router = createHashRouter([
    {
        path: "/",
        element: <Dashboard />,
        errorElement: <Login />,
        loader: fetchAdminLoader,
    },
    {
        path: "/commerce/",
        element: <CommerceAdmin />,
        errorElement: <Login />,
        loader: fetchAdminLoader,
    },
    {
        path: "/login/",
        element: <Login />,
    },
    {
        path: "/portal/",
        element: <PortalLayout />,
        errorElement: <PortalError />,
        loader: fetchPortalLoader,
        children: [
            { index: true, element: <PortalOverview /> },
            { path: "plans", element: <PortalPlans /> },
            { path: "access", element: <PortalAccess /> },
            { path: "wallet", element: <PortalWallet /> },
        ],
    },
    {
        path: "/portal/login/",
        element: <PortalLogin />,
    },
    {
        path: "/portal/register/",
        element: <PortalRegister />,
    },
]);
