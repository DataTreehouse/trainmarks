FROM mcr.microsoft.com/dotnet/sdk:10.0
WORKDIR /app
COPY Verify.csproj .
RUN dotnet restore
COPY Program.cs .
RUN dotnet build -c Release -o /app/out
ENTRYPOINT ["dotnet", "/app/out/Verify.dll"]
