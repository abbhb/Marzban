import { Box } from "@chakra-ui/react";
import { Suspense } from "react";
import { RouterProvider } from "react-router-dom";
import { router } from "./pages/Router";

function App() {
    return (
        <Box
            minH="100dvh"
            position="relative"
            overflowX="clip"
            color="text.primary"
        >
            <Suspense fallback={null}>
                <RouterProvider router={router} fallbackElement={null} />
            </Suspense>
        </Box>
    );
}

export default App;
