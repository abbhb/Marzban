import "react-datepicker/dist/react-datepicker.css";
import "react-loading-skeleton/dist/skeleton.css";
import { Box } from "@chakra-ui/react";
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
            <RouterProvider router={router} />
        </Box>
    );
}

export default App;
