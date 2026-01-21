import React, { useCallback, useMemo } from 'react'
import { useDropzone } from 'react-dropzone'
import { Box, Typography, Paper } from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'

const FileUploader = ({ accept = '.pdf', onFileSelect, maxFiles = 1, multiple = false }) => {
  const onDrop = useCallback(
    (acceptedFiles) => {
      if (acceptedFiles.length > 0) {
        if (maxFiles === 1 && !multiple) {
          onFileSelect(acceptedFiles[0])
        } else {
          onFileSelect(acceptedFiles)
        }
      }
    },
    [onFileSelect, maxFiles, multiple]
  )

  // Convert accept string to proper MIME type mapping
  const acceptConfig = useMemo(() => {
    const extensions = accept.split(',').map(ext => ext.trim())
    const mimeTypes = {}

    extensions.forEach(ext => {
      if (ext === '.pdf' || ext === 'pdf') {
        mimeTypes['application/pdf'] = ['.pdf']
      } else if (ext === '.json' || ext === 'json') {
        mimeTypes['application/json'] = ['.json']
      } else if (ext === '.zip' || ext === 'zip') {
        mimeTypes['application/zip'] = ['.zip']
      } else {
        // Generic handling for other extensions
        if (!mimeTypes['*/*']) {
          mimeTypes['*/*'] = []
        }
        mimeTypes['*/*'].push(ext.startsWith('.') ? ext : `.${ext}`)
      }
    })

    return mimeTypes
  }, [accept])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: acceptConfig,
    maxFiles,
    multiple: maxFiles > 1 || multiple,
  })

  return (
    <Paper
      {...getRootProps()}
      sx={{
        p: 4,
        textAlign: 'center',
        cursor: 'pointer',
        border: '2px dashed',
        borderColor: isDragActive ? 'primary.main' : 'grey.300',
        bgcolor: isDragActive ? 'action.hover' : 'background.paper',
        transition: 'all 0.2s',
        '&:hover': {
          borderColor: 'primary.main',
          bgcolor: 'action.hover',
        },
      }}
    >
      <input {...getInputProps()} />
      <CloudUploadIcon sx={{ fontSize: 48, color: 'primary.main', mb: 2 }} />
      <Typography variant="h6" gutterBottom>
        {isDragActive ? 'Drop the file here' : 'Drag & drop file here'}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        or click to select {maxFiles === 1 ? 'a file' : 'files'}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
        Accepted formats: {accept}
      </Typography>
    </Paper>
  )
}

export default FileUploader
