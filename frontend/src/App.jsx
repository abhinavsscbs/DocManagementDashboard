import React from 'react'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import Box from '@mui/material/Box'
import Container from '@mui/material/Container'
import Typography from '@mui/material/Typography'
import Paper from '@mui/material/Paper'
import Alert from '@mui/material/Alert'
import { useApp } from './context/AppContext'
import Sidebar from './components/Layout/Sidebar'
import Header from './components/Layout/Header'
import EYPipeline from './components/Pipelines/EYPipeline'
import PwCPipeline from './components/Pipelines/PwCPipeline'
import IFRSPipeline from './components/Pipelines/IFRSPipeline'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc004e',
    },
  },
})

function App() {
  const { selectedPipeline, error } = useApp()

  const renderPipeline = () => {
    switch (selectedPipeline) {
      case 'ey':
        return <EYPipeline />
      case 'pwc':
        return <PwCPipeline />
      case 'ifrs':
        return <IFRSPipeline />
      default:
        return <EYPipeline />
    }
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', minHeight: '100vh' }}>
        <Sidebar />
        <Box
          component="main"
          sx={{
            flexGrow: 1,
            bgcolor: 'background.default',
            p: 3,
          }}
        >
          <Header />

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => {}}>
              {error}
            </Alert>
          )}

          <Container maxWidth="xl">
            {renderPipeline()}
          </Container>
        </Box>
      </Box>
    </ThemeProvider>
  )
}

export default App
