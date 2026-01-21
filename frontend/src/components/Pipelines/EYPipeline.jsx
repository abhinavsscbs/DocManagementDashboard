import React, { useState } from 'react'
import {
  Paper,
  Typography,
  Button,
  Box,
  Alert,
  CircularProgress,
  LinearProgress,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Divider,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import FileUploader from '../FileUpload/FileUploader'

const EYPipeline = () => {
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [results, setResults] = useState(null)
  const [processingStage, setProcessingStage] = useState('')

  const handleFileSelect = (selectedFile) => {
    setFile(selectedFile)
    setMessage(null)
    setResults(null)
  }

  const handleProcess = async () => {
    if (!file) {
      setMessage({ type: 'error', text: 'Please select a PDF or JSON file' })
      return
    }

    setLoading(true)
    setMessage(null)
    setResults(null)
    setProcessingStage('Uploading file...')

    try {
      const formData = new FormData()
      formData.append('file', file)

      setTimeout(() => setProcessingStage('Processing PDF and extracting content...'), 1000)

      const response = await fetch('/api/process/ey', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (response.ok) {
        setResults(data)
        setMessage({
          type: 'success',
          text: `Database updated successfully! Processing time: ${data.processing_time_minutes} minutes`
        })
      } else {
        setMessage({
          type: 'error',
          text: data.message || data.error || 'Processing failed'
        })
      }
    } catch (error) {
      setMessage({ type: 'error', text: error.message })
    } finally {
      setLoading(false)
      setProcessingStage('')
    }
  }

  const downloadCSV = async () => {
    if (!results?.download_token) return
    try {
      const response = await fetch(`/api/download/csv/${results.download_token}`)
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'ey_chunks_preview.csv'
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      }
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        EY Pipeline
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Upload a single EY International GAAP PDF or JSON file for processing
      </Typography>

      <Box sx={{ my: 3 }}>
        <FileUploader
          accept=".pdf,.json"
          onFileSelect={handleFileSelect}
          maxFiles={1}
        />
      </Box>

      {file && (
        <Typography variant="body2" sx={{ mb: 2 }}>
          Selected: {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
        </Typography>
      )}

      {message && (
        <Alert severity={message.type} sx={{ mb: 2 }}>
          {message.text}
        </Alert>
      )}

      {loading && (
        <Box sx={{ mb: 2 }}>
          <LinearProgress />
          <Box sx={{ display: 'flex', alignItems: 'center', mt: 1 }}>
            <CircularProgress size={16} sx={{ mr: 1 }} />
            <Typography variant="body2" color="text.secondary">
              {processingStage}
            </Typography>
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            This typically takes 2-5 minutes depending on file size.
          </Typography>
        </Box>
      )}

      <Button
        variant="contained"
        startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <CloudUploadIcon />}
        onClick={handleProcess}
        disabled={!file || loading}
        size="large"
        fullWidth
      >
        {loading ? 'Processing...' : 'Process EY Document'}
      </Button>

      {results && (
        <Box sx={{ mt: 3 }}>
          <Divider sx={{ my: 2 }} />

          <Typography variant="h6" gutterBottom>
            Results
          </Typography>

          <Box sx={{ mb: 2 }}>
            <Chip
              label={`Chunks extracted: ${results.chunks_count}`}
              color="primary"
              sx={{ mr: 1, mb: 1 }}
            />
            <Chip
              label={`Processing time: ${results.processing_time_minutes} minutes`}
              color="secondary"
              sx={{ mr: 1, mb: 1 }}
            />
            <Chip
              label={results.doc_name}
              variant="outlined"
              sx={{ mb: 1 }}
            />
          </Box>

          <Button
            variant="outlined"
            onClick={downloadCSV}
            size="small"
            sx={{ mb: 2 }}
          >
            ⬇️ Download CSV
          </Button>

          {results.preview_data && results.preview_data.length > 0 && (
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography>Preview (top {Math.min(1000, results.preview_data.length)} rows)</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <TableContainer component={Paper} sx={{ maxHeight: 600 }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Header</TableCell>
                        <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Page</TableCell>
                        <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Chapter</TableCell>
                        <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Paragraph</TableCell>
                        <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Preprocessed</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {results.preview_data.map((row, idx) => (
                        <TableRow
                          key={idx}
                          sx={{
                            '&:nth-of-type(odd)': { bgcolor: 'grey.50' },
                            '&:hover': { bgcolor: 'action.hover' }
                          }}
                        >
                          <TableCell sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {row.header}
                          </TableCell>
                          <TableCell>{row.page}</TableCell>
                          <TableCell sx={{ maxWidth: 150 }}>{row.chapter_name}</TableCell>
                          <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                            {row.para}
                          </TableCell>
                          <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                            {row.preprocessed}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </AccordionDetails>
            </Accordion>
          )}
        </Box>
      )}
    </Paper>
  )
}

export default EYPipeline
