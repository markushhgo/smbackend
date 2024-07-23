$resourceGroup = "turku-dev"
$registry = "turkudev"
$image = "turku-dev-servicemap-api"
$webApp = "turku-dev-servicemap-api"

function Test-NetConnectionFaster($Addr, [int] $Port) {
  $TCPClient = [System.Net.Sockets.TcpClient]::new()
  $result = $TCPClient.ConnectAsync($Addr, $Port).Wait(100)
  $TCPClient.Close()
  return $result
}
function Open-AzureWebAppSshConnection {
  $command = "az webapp create-remote-connection --resource-group $resourceGroup --name $webApp -p 59123"
  $job = Start-Job -ScriptBlock { Invoke-Expression $using:command }
  return $job.Id
}
function Test-AzureWebAppSshConnection {
  return Test-NetConnectionFaster 127.0.0.1 59123
}
function Open-AzureWebAppSsh {
    "Connecting to Azure WebApp... if this stalls, might need to run 'AzureUtil config ENABLE_SSH=true'"
    $jobId = Open-AzureWebAppSshConnection
    ssh-keygen -R [localhost]:59123 >nul 2>&1
    do {
        Start-Sleep -Milliseconds 10
    } until (Test-AzureWebAppSshConnection)
    "Connected, establishing SSH terminal. The password is 'Docker!'"
    ssh root@localhost -p 59123 -o StrictHostKeyChecking=no
    Stop-Job $jobId
}

switch ($args[0]) {
    "build" {
        az acr build --resource-group $resourceGroup --registry $registry --image $image .
    }
    "log" {
        az webapp log tail --resource-group $resourceGroup --name $webApp
    }
    "config" {
        switch ($args[1]) {
            $null {
                az webapp config appsettings list --resource-group $resourceGroup --name $webApp | ConvertFrom-Json | Sort-Object -Property name | ForEach-Object { "$($_.name)=$($_.value)" }
            }
            "delete" {
                az webapp config appsettings delete --resource-group $resourceGroup --name $webApp --setting-names ($args | Select-Object -Skip 1)
            }
            Default {
                az webapp config appsettings set --resource-group $resourceGroup --name $webApp --settings ($args | Select-Object -Skip 1)
            }
        }
    }
    "ssh" {
        Open-AzureWebAppSsh
    }
    Default {
       "Usage:"
       ""
       "./AzureUtil build"
       "`tBuild a new image in the WebApp's Azure container registry"
       "./AzureUtil log"
       "`tView the WebApp's log stream"
       "./AzureUtil ssh"
       "`tAccess the WebApp's SSH, assuming one is set up in docker-entrypoint"
       "./AzureUtil config"
       "`tShow the WebApp's environment variables in a .env file format"
       "./AzureUtil config setting1=value1 setting2=value2 ..."
       "`tAssign the given values in the WebApp's environment variables"
       "./AzureUtil config delete setting1 setting2 ..."
       "`tDelete the given keys from the WebApp's environment variables"
    }
}