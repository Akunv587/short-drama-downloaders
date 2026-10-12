package com.shortmaxdl.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.shortmaxdl.domain.model.DownloadStatus
import com.shortmaxdl.domain.model.DownloadTaskState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DownloadScreen(
    viewModel: MainViewModel,
    onBack: () -> Unit,
) {
    val taskStates by viewModel.taskStates.collectAsState()
    val isRunning by viewModel.isDownloadRunning.collectAsState()
    val uiState by viewModel.uiState.collectAsState()

    val taskList = taskStates.values.sortedBy { it.episodeNumber }
    val completedCount = taskList.count { it.status == DownloadStatus.COMPLETED }
    val totalCount = taskList.size

    LaunchedEffect(isRunning) {
        if (!isRunning && totalCount > 0) {
            viewModel.onDownloadFinished()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "下载队列 ($completedCount/$totalCount)",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                )
            )
        },
        bottomBar = {
            if (totalCount > 0 && (isRunning || taskList.any {
                it.status == DownloadStatus.PAUSED
            })) {
                Surface(
                    color = MaterialTheme.colorScheme.surface,
                    shadowElevation = 8.dp,
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                    ) {
                        OutlinedButton(
                            onClick = viewModel::pauseDownload,
                            enabled = isRunning,
                        ) {
                            Icon(Icons.Default.Pause, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("全部暂停")
                        }
                        Button(
                            onClick = viewModel::resumeDownload,
                            enabled = !isRunning && !taskList.all {
                                it.status == DownloadStatus.COMPLETED
                            },
                        ) {
                            Icon(Icons.Default.PlayArrow, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("全部开始")
                        }
                        OutlinedButton(
                            onClick = viewModel::stopDownload,
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = MaterialTheme.colorScheme.error,
                            ),
                        ) {
                            Icon(Icons.Default.Stop, contentDescription = null)
                            Spacer(Modifier.width(8.dp))
                            Text("终止")
                        }
                    }
                }
            }
        }
    ) { padding ->
        if (taskList.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "暂无下载任务",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
            ) {
                items(taskList) { task ->
                    DownloadTaskItem(task = task, viewModel = viewModel)
                }
            }
        }
    }
}

@Composable
private fun DownloadTaskItem(
    task: DownloadTaskState,
    viewModel: MainViewModel,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Status icon
            val (icon, tint) = when (task.status) {
                DownloadStatus.COMPLETED -> Icons.Default.CheckCircle to MaterialTheme.colorScheme.primary
                DownloadStatus.DOWNLOADING -> Icons.Default.Download to MaterialTheme.colorScheme.secondary
                DownloadStatus.QUEUED -> Icons.Default.HourglassEmpty to MaterialTheme.colorScheme.onSurfaceVariant
                DownloadStatus.FAILED -> Icons.Default.Error to MaterialTheme.colorScheme.error
                DownloadStatus.PAUSED -> Icons.Default.PauseCircle to MaterialTheme.colorScheme.onSurfaceVariant
                DownloadStatus.RETRYING -> Icons.Default.Refresh to MaterialTheme.colorScheme.secondary
            }

            Icon(
                icon,
                contentDescription = task.status.name,
                tint = tint,
                modifier = Modifier.size(28.dp),
            )

            Spacer(Modifier.width(12.dp))

            // Info
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "E${task.episodeNumber.toString().padStart(2, '0')}",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        task.movieTitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }

                Spacer(Modifier.height(4.dp))

                // Status text
                when (task.status) {
                    DownloadStatus.DOWNLOADING -> {
                        Column {
                            LinearProgressIndicator(
                                progress = { task.progressPercent / 100f },
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Spacer(Modifier.height(2.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    "${"%.1f".format(task.progressPercent)}%",
                                    style = MaterialTheme.typography.labelSmall,
                                )
                                Text(
                                    formatSpeed(task.speedBytesPerSec),
                                    style = MaterialTheme.typography.labelSmall,
                                )
                            }
                        }
                    }

                    DownloadStatus.COMPLETED -> {
                        val sizeMb = task.fileSizeBytes / 1024.0 / 1024.0
                        Text(
                            "完成 — ${"%.1f".format(sizeMb)} MB",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }

                    DownloadStatus.FAILED -> {
                        Text(
                            task.errorMessage ?: "下载失败",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.error,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }

                    DownloadStatus.QUEUED -> Text("等待中...", style = MaterialTheme.typography.labelSmall)
                    DownloadStatus.PAUSED -> Text("已暂停", style = MaterialTheme.typography.labelSmall)
                    DownloadStatus.RETRYING -> Text(
                        "重试中 (${task.attempt})",
                        style = MaterialTheme.typography.labelSmall
                    )
                }
            }

            // Retry button for failed tasks
            AnimatedVisibility(visible = task.status == DownloadStatus.FAILED) {
                IconButton(
                    onClick = {
                        // Find the episode from current state and retry
                        val uiState = viewModel.uiState.value
                        val ep = uiState.episodes.find { it.episodeNumber == task.episodeNumber }
                        if (ep != null) viewModel.retryEpisode(ep)
                    }
                ) {
                    Icon(Icons.Default.Refresh, "重试")
                }
            }
        }
    }
}

private fun formatSpeed(bps: Long): String {
    if (bps <= 0) return ""
    return when {
        bps >= 1_000_000 -> "${"%.1f".format(bps / 1_000_000.0)} MB/s"
        bps >= 1_000 -> "${"%.1f".format(bps / 1_000.0)} KB/s"
        else -> "$bps B/s"
    }
}
