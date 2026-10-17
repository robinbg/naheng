param(
 [Parameter(Mandatory=$true)][string]$Url,
 [Parameter(Mandatory=$true)][int]$MaximumBytes,
 [ValidateSet('GET','HEAD')][string]$Method='GET',
 [string]$Range=''
)
$ErrorActionPreference='Stop'
$result=@{bytes_received=0;tls='Windows default certificate and hostname validation'}
try {
 $uri=[Uri]$Url
 if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'publications.rwth-aachen.de' -or
     -not ($uri.AbsolutePath -eq '/record/987579' -or $uri.AbsolutePath.StartsWith('/record/987579/')) -or $uri.UserInfo) {
  throw 'Source URL is not allowlisted'
 }
 if ($Range -and $Range -notmatch '^bytes=\d+-\d+$') { throw 'Invalid bounded range' }
 $handler=[System.Net.Http.HttpClientHandler]::new()
 $handler.AllowAutoRedirect=$false
 $handler.UseDefaultCredentials=$false
 $client=[System.Net.Http.HttpClient]::new($handler)
 $client.Timeout=[TimeSpan]::FromSeconds(30)
 $request=[System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method),$Url)
 $null=$request.Headers.TryAddWithoutValidation('User-Agent','naheng-public-data-audit/0.1')
 $null=$request.Headers.TryAddWithoutValidation('Accept-Encoding','identity')
 if ($Range) { $null=$request.Headers.TryAddWithoutValidation('Range',$Range) }
 $response=$client.SendAsync($request,[System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
 $result.status=[int]$response.StatusCode
 $headers=@{}
 foreach ($entry in $response.Headers) { $headers[$entry.Key]=($entry.Value -join ', ') }
 foreach ($entry in $response.Content.Headers) { $headers[$entry.Key]=($entry.Value -join ', ') }
 $result.response_headers=$headers
 $result.resolved_url=$Url
 if ($Range -and $result.status -ne 206) { throw 'Archive server did not return 206; body stream was not read' }
 if ($result.status -lt 200 -or $result.status -ge 300) { throw "HTTP status $($result.status)" }
 if ($Method -eq 'HEAD') { $result.body_base64='' }
 else {
  if ($response.Content.Headers.ContentLength -and $response.Content.Headers.ContentLength -gt $MaximumBytes) {
   throw 'Declared response length exceeds hard byte limit; body stream was not read'
  }
  $stream=$response.Content.ReadAsStream()
  $memory=[IO.MemoryStream]::new()
  $buffer=[byte[]]::new(65536)
  while ($true) {
   $allowed=[Math]::Min($buffer.Length,$MaximumBytes-$memory.Length)
   if ($allowed -le 0) {
    if ($response.Content.Headers.ContentLength -eq $memory.Length) { break }
    throw 'Cannot verify response completeness within hard byte limit' 
   }
   $count=$stream.Read($buffer,0,$allowed)
   if ($count -eq 0) { break }
   $memory.Write($buffer,0,$count)
   $result.bytes_received=[int]$memory.Length
  }
  $result.bytes_received=[int]$memory.Length
  $result.body_base64=[Convert]::ToBase64String($memory.ToArray())
  $stream.Dispose()
  $memory.Dispose()
 }
}
catch { $result.error=$_.Exception.Message }
finally {
 if ($response) { $response.Dispose() }
 if ($client) { $client.Dispose() }
}
$result | ConvertTo-Json -Depth 5 -Compress
